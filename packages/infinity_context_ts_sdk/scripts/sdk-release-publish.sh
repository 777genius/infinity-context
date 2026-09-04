#!/usr/bin/env bash
set -euo pipefail

# This helper is intentionally effect-aware: every release mutation is below the
# complete state, tag, ruleset, transport, and CLI preflight performed by the workflow.

die() {
  printf '%s\n' "$*" >&2
  exit 1
}

required_env() {
  local name="$1"
  [ -n "${!name:-}" ] || die "${name} is required"
}

for name in GITHUB_OUTPUT GITHUB_REPOSITORY GITHUB_RUN_ATTEMPT GITHUB_RUN_ID \
  GITHUB_WORKSPACE RELEASE_COMMIT RELEASE_TAG SDK_ARTIFACT SDK_VERSION TAG_OBJECT \
  WORKFLOW_SHA256; do
  required_env "${name}"
done

case "${RECONCILE_ONLY:-false}" in
  true|false) ;;
  *) die "RECONCILE_ONLY must be true or false" ;;
esac
case "${RELEASE_POLL_SECONDS:-5}" in
  0|1|2|3|4|5) ;;
  *) die "RELEASE_POLL_SECONDS must be between zero and five" ;;
esac
if [ "${GITHUB_REPOSITORY}" != "777genius/infinity-context" ]; then
  die "Release repository identity is not 777genius/infinity-context"
fi
if [ -n "${SDK_RELEASE_ADMIN_READ_TOKEN:-}" ]; then
  die "The administration-read token must never enter the publish job"
fi

api_get() {
  gh api --method GET -H "Accept: application/vnd.github+json" "$1"
}

revalidate_tag_and_ruleset() {
  local item ref ruleset_id ruleset_summaries rulesets tag_json
  ref="$(api_get "repos/${GITHUB_REPOSITORY}/git/ref/tags/${RELEASE_TAG}")"
  test "$(jq -er '.object.type' <<<"${ref}")" = tag
  test "$(jq -er '.object.sha' <<<"${ref}")" = "${TAG_OBJECT}"
  tag_json="$(api_get "repos/${GITHUB_REPOSITORY}/git/tags/${TAG_OBJECT}")"
  test "$(jq -er '.object.type' <<<"${tag_json}")" = commit
  test "$(jq -er '.object.sha' <<<"${tag_json}")" = "${RELEASE_COMMIT}"

  ruleset_summaries="$(gh api --method GET --paginate --slurp \
    -H "Accept: application/vnd.github+json" \
    "repos/${GITHUB_REPOSITORY}/rulesets?targets=tag&per_page=100")"
  rulesets='[]'
  while IFS= read -r ruleset_id; do
    [ -n "${ruleset_id}" ] || continue
    item="$(api_get \
      "repos/${GITHUB_REPOSITORY}/rulesets/${ruleset_id}?includes_parents=true")"
    rulesets="$(jq --argjson item "${item}" '. + [$item]' <<<"${rulesets}")"
  done < <(jq -er '.[][] | .id' <<<"${ruleset_summaries}")
  jq -e --arg ref "refs/tags/${RELEASE_TAG}" '
    [ .[]
      | select(.target == "tag" and .enforcement == "active")
      | select((([.rules[].type] | index("creation")) != null) and
               (([.rules[].type] | index("update")) != null) and
               (([.rules[].type] | index("deletion")) != null))
      | .conditions.ref_name as $names
      | select(($names.exclude | length) == 0)
      | select(any($names.include[]?;
          . == "~ALL" or . == $ref or
          (. == "refs/tags/sdk-v*" and ($ref | startswith("refs/tags/sdk-v")))))
    ] | length > 0
  ' <<<"${rulesets}" >/dev/null
}

# The releases-by-tag endpoint does not reliably expose drafts. Scan at most 1,000
# releases and fail closed instead of treating an unbounded or malformed inventory
# as absence.
inspect_release() {
  local count page page_number releases
  releases='[]'
  for page_number in 1 2 3 4 5 6 7 8 9 10; do
    page="$(api_get \
      "repos/${GITHUB_REPOSITORY}/releases?per_page=100&page=${page_number}")"
    jq -e 'type == "array"' <<<"${page}" >/dev/null || die "Malformed release inventory"
    releases="$(jq --argjson page "${page}" '. + $page' <<<"${releases}")"
    if [ "$(jq -r 'length' <<<"${page}")" -lt 100 ]; then
      break
    fi
    [ "${page_number}" -lt 10 ] || die "Release inventory exceeds the bounded scan"
  done
  RELEASE_JSON="$(jq --arg tag "${RELEASE_TAG}" '[.[] | select(.tag_name == $tag)]' \
    <<<"${releases}")"
  count="$(jq -r 'length' <<<"${RELEASE_JSON}")"
  case "${count}" in
    0) RELEASE_STATE=absent ;;
    1)
      RELEASE_JSON="$(jq -c '.[0]' <<<"${RELEASE_JSON}")"
      if ! jq -e 'type == "object" and (.draft | type) == "boolean"' \
        <<<"${RELEASE_JSON}" >/dev/null; then
        RELEASE_STATE=malformed
      elif [ "$(jq -r '.draft' <<<"${RELEASE_JSON}")" = true ]; then
        RELEASE_STATE=draft
      else
        RELEASE_STATE=published
      fi
      ;;
    *) RELEASE_STATE=malformed ;;
  esac
}

validate_release_shape() {
  local expected_draft="$1"
  jq -e \
    --arg artifact "${SDK_ARTIFACT}" \
    --arg manifest infinity-context-sdk-release-manifest.json \
    --arg repository "${GITHUB_REPOSITORY}" \
    --arg tag "${RELEASE_TAG}" \
    --arg title "Infinity Context TypeScript SDK ${SDK_VERSION}" \
    --argjson draft "${expected_draft}" '
      type == "object" and
      (.id | type) == "number" and (.id > 0) and
      .tag_name == $tag and .name == $title and
      .draft == $draft and .prerelease == false and
      .html_url == ("https://github.com/" + $repository + "/releases/tag/" + $tag) and
      (.assets | type) == "array" and (.assets | length) == 2 and
      ([.assets[].name] | sort) == ([$artifact, $manifest] | sort) and
      (all(.assets[]; (.id | type) == "number" and (.id > 0)))
    ' <<<"${RELEASE_JSON}" >/dev/null || die "Release identity or asset set is malformed"
  if [ "${expected_draft}" = false ]; then
    jq -e '(.immutable == true) and
      all(.assets[];
        (.digest | type) == "string" and
        (.digest | test("^sha256:[0-9a-f]{64}$")))' \
      <<<"${RELEASE_JSON}" >/dev/null || die "Published release is mutable or lacks exact digests"
  fi
}

assets=("${SDK_ARTIFACT}" infinity-context-sdk-release-manifest.json)
inspect_release
case "${RELEASE_STATE}" in
  absent)
    [ "${RECONCILE_ONLY:-false}" = false ] || \
      die "Reconcile-only mode requires an existing published release"
    revalidate_tag_and_ruleset
    GH_REPO="${GITHUB_REPOSITORY}" gh release create "${RELEASE_TAG}" \
      --draft --latest=false --notes-from-tag \
      --title "Infinity Context TypeScript SDK ${SDK_VERSION}" --verify-tag
    for asset in "${assets[@]}"; do
      gh release upload "${RELEASE_TAG}" "release-bundle/${asset}" \
        --repo "${GITHUB_REPOSITORY}"
    done
    inspect_release
    [ "${RELEASE_STATE}" = draft ] || die "Created release did not remain one exact draft"
    validate_release_shape true
    ;;
  published)
    revalidate_tag_and_ruleset
    validate_release_shape false
    ;;
  draft) die "An existing draft is non-resumable" ;;
  malformed) die "Existing release state is malformed or duplicated" ;;
  *) die "Unexpected release state" ;;
esac

mkdir verification-receipt
for asset in "${assets[@]}"; do
  gh release download "${RELEASE_TAG}" --repo "${GITHUB_REPOSITORY}" \
    --pattern "${asset}" --dir verification-receipt
  cmp "release-bundle/${asset}" "verification-receipt/${asset}" || {
    if [ "${asset}" = "${SDK_ARTIFACT}" ]; then
      die "Published SDK artifact differs from the pack-once build"
    fi
    [ "${RELEASE_STATE}" = published ] || die "Uploaded manifest bytes changed"
  }
done

if [ "${RELEASE_STATE}" = published ]; then
  origin_run_id="$(jq -er '.build_workflow_run_id | select(type == "number" and . > 0)' \
    verification-receipt/infinity-context-sdk-release-manifest.json)"
  origin_run_attempt="$(jq -er '.build_workflow_run_attempt | select(type == "number" and . > 0)' \
    verification-receipt/infinity-context-sdk-release-manifest.json)"
  node packages/infinity_context_ts_sdk/scripts/sdk-release-manifest.mjs \
    --artifact "${GITHUB_WORKSPACE}/verification-receipt/${SDK_ARTIFACT}" \
    --artifact-root "${GITHUB_WORKSPACE}/verification-receipt" \
    --build-profile node24-npm-ci-pack-once.v1 \
    --manifest "${GITHUB_WORKSPACE}/verification-receipt/infinity-context-sdk-release-manifest.json" \
    --node-version 24.18.0 \
    --output-root "${GITHUB_WORKSPACE}/verification-receipt" \
    --package-root "${GITHUB_WORKSPACE}/packages/infinity_context_ts_sdk" \
    --repository "${GITHUB_REPOSITORY}" \
    --repository-root "${GITHUB_WORKSPACE}" \
    --tag "${RELEASE_TAG}" \
    --workflow-path .github/workflows/typescript-sdk-release.yml \
    --workflow-run-attempt "${origin_run_attempt}" \
    --workflow-run-id "${origin_run_id}" \
    --workflow-sha256 "${WORKFLOW_SHA256}"
else
  revalidate_tag_and_ruleset
  set +e
  gh release edit "${RELEASE_TAG}" --repo "${GITHUB_REPOSITORY}" --draft=false
  edit_status=$?
  set -e
  for attempt in 1 2 3 4 5 6; do
    inspect_release
    if [ "${RELEASE_STATE}" = published ]; then
      validate_release_shape false
      break
    fi
    [ "${RELEASE_STATE}" = draft ] || \
      die "Publication reconciliation found ${RELEASE_STATE} release state"
    if [ "${attempt}" -eq 6 ]; then
      if [ "${edit_status}" -ne 0 ]; then
        die "Publication outcome remained ambiguous after a failed edit request"
      fi
      die "Published release did not become immutable"
    fi
    sleep "${RELEASE_POLL_SECONDS:-5}"
  done
fi

printf '%s\n' "${RELEASE_JSON}" >verification-receipt/release.json
release_attestation="$(gh release verify "${RELEASE_TAG}" \
  --repo "${GITHUB_REPOSITORY}" --format json)"
jq -e 'type == "object"' <<<"${release_attestation}" >/dev/null
printf '%s\n' "${release_attestation}" \
  >verification-receipt/release-attestation.json
for asset in "${assets[@]}"; do
  asset_attestation="$(gh release verify-asset "${RELEASE_TAG}" \
    "verification-receipt/${asset}" --repo "${GITHUB_REPOSITORY}" --format json)"
  jq -e 'type == "object"' <<<"${asset_attestation}" >/dev/null
  printf '%s\n' "${asset_attestation}" \
    >"verification-receipt/${asset}.attestation.json"
done
printf 'url=%s\n' "$(jq -er '.html_url' <<<"${RELEASE_JSON}")" >>"${GITHUB_OUTPUT}"
