# TypeScript SDK releases

`@infinity-context/sdk` releases independently from the Infinity service and meeting
quality cadence. The SDK release binds source, contracts, lockfile, build workflow,
and one exact npm tarball. It does not qualify a service, deployment, embedding/index,
model/runtime, corpus, or meeting outcome.

An SDK release contains exactly two assets:

```text
infinity-context-sdk-X.Y.Z.tgz
infinity-context-sdk-release-manifest.json
```

The workflow uses Node 24.18.0 and `npm ci`, runs architecture, parity, type, test,
build, and export checks, then calls `npm pack` exactly once. The consumer smoke is
given that same file with `check-consumer-install.mjs --artifact`; it cannot silently
replace the release bytes with another pack.

## Operator prerequisites

Administrators must configure these controls before dispatch. The workflow checks
GitHub's dedicated repository immutable-releases endpoint and requires its documented
`enabled: true` response; it fails closed and never changes repository settings or
invents credentials.

- Enable repository immutable releases.
- Create a fine-grained `SDK_RELEASE_ADMIN_READ_TOKEN` secret scoped only to this
  repository with **Administration: read-only** permission. Store it only in the
  protected `sdk-release-policy` environment. That environment is used by a separate
  one-step job with `permissions: {}`. It has no checkout, action, setup, downloaded
  artifact, or repository-controlled runtime step before the authenticated policy
  GET, and it exports no token or policy contents. The downstream publish job has no
  environment or secret reference and can never receive the token.
- Create an active tag ruleset covering `refs/tags/sdk-v*` that restricts creation,
  update, and deletion. Release tags are existing annotated tags pointing directly to
  a commit.
- Create the protected `sdk-release-policy` environment with required independent
  review, self-review prevention, deployment restrictions for protected SDK tags,
  and only the administration-read secret. Its successful reviewed preflight gates
  the downstream contents-write job, which starts automatically to minimize delay.
- Restrict manual Actions dispatch and tag bypass authority to release operators.
- Keep the repository identity `777genius/infinity-context` and permit the protected
  publish job to write contents.

The build job has `contents: read`. After it succeeds, the protected policy job has
no repository permission, and the gated publish job has `contents: write` only;
artifact upload/download, including the verification receipt, does not require an
`actions: write` grant. No job has registry, OIDC, provider, Discord, or service
credentials.

## Manifest contract

`infinity-context-sdk-release-manifest.json` is canonical key-sorted JSON, has no
timestamp, and is exclusively created. Its workflow-facing CLI accepts required flags
only; it derives Git identities from the checkout and has no manual revision override.
It binds:

- repository name and HTTPS URL;
- annotated release tag and tag object;
- source commit, source tree, and Git object format;
- package name/version (minimum 0.2.1);
- tarball filename, byte length, SHA-256, and SHA-512 SRI;
- `package-lock.json` SHA-256;
- Node 24.18.0 and `node24-npm-ci-pack-once.v1` build profile;
- a path/digest inventory of SDK TypeScript contracts and JSON fixtures, plus its
  canonical inventory digest;
- exact workflow path, workflow blob SHA-256, Actions run ID, and run attempt.

The manifest has no service revision, capability fingerprint, qualification data,
model/runtime/corpus identity, meeting outcome, Discord data, private evidence, or
timestamp. Inputs and evidence must be bounded regular files under their declared
roots. Symlinks, path escapes, duplicate-key/noncanonical JSON, unsafe numbers,
newline output injection, and output overwrite are rejected.

## Executable release runbook for 0.2.1

Start from the reviewed release commit. Create and push the one protected annotated
tag; the workflow never creates or moves it:

```bash
git status --short
test "$(node -p "require('./packages/infinity_context_ts_sdk/package.json').version")" = 0.2.1
git tag -a sdk-v0.2.1 -m "Infinity Context TypeScript SDK 0.2.1" <REVIEWED_COMMIT_SHA>
git push origin refs/tags/sdk-v0.2.1
```

Dispatch only that exact tag and record the run URL:

```bash
gh workflow run .github/workflows/typescript-sdk-release.yml \
  --repo 777genius/infinity-context \
  --ref sdk-v0.2.1 \
  -f sdk_tag=sdk-v0.2.1 \
  -f reconcile_only=false
gh run list --repo 777genius/infinity-context \
  --workflow .github/workflows/typescript-sdk-release.yml --limit 1
```

The dispatch ref and `sdk_tag` must be the same exact annotated tag. The workflow
rejects default-branch dispatch, resolves the tag object and commit, and requires
`github.workflow_sha` to equal that commit. Consequently the manifest hashes the
workflow file from the same reviewed commit that GitHub executed.

Approve `sdk-release-policy` only after the build job succeeds. The isolated policy
job uses the administration-read secret to confirm
the immutable-release setting. It runs after the expensive build to shorten the gap
to publication. GitHub offers no transaction spanning this administration read and a
later release write, so a privileged administrator could still disable the setting
between them. The publish job minimizes the remaining interval, requires the release
it observes after publication to be immutable, and fails closed if the policy/effect
race is lost; operators must investigate that terminal state rather than edit it.

The publish job rehashes and semantically revalidates both transported files and first
requires the installed
`gh` to expose the exact `gh release verify [<tag>]` and
`gh release verify-asset [<tag>] <file-path>` syntax used by the workflow, including
`--repo` and JSON output. The effect helper inspects a bounded release inventory and
distinguishes absence, draft, published, duplicate/malformed, and over-bound states.
An absent release follows the create path. Any draft or malformed state is
non-resumable. An exact published release follows a read-only reconciliation path.
Immediately before draft creation and publication, the helper revalidates the exact
annotated tag object, commit, and active creation/update/deletion ruleset. It creates
one draft, uploads without `--clobber`, downloads and compares both assets, attempts
publication once, and then reconciles the server state for at most six observations
even when `gh release edit` reports failure. It never recreates or reuploads during
reconciliation.

If a runner is lost after GitHub accepts publication, rerun the same dispatch. A
normal retry recognizes an exact published release and reconciles it instead of
blindly rejecting it. For an explicitly effect-free recovery dispatch, use the same
exact tag with:

```bash
gh workflow run .github/workflows/typescript-sdk-release.yml \
  --repo 777genius/infinity-context \
  --ref sdk-v0.2.1 \
  -f sdk_tag=sdk-v0.2.1 \
  -f reconcile_only=true
```

Reconcile-only mode rejects absence and never creates, uploads, edits, deletes, or
publishes. It downloads the exact existing two assets, compares the tarball to the
fresh pack-once build, semantically verifies the released manifest using its original
run ID/attempt, rechecks tag/ruleset state, and requires the release to be published,
immutable, and structurally exact.

## Download, verify, and cold install

The immutable release URL is a dependency: do not use a branch archive or Actions
artifact as distribution. Download and verify the exact two assets:

```bash
mkdir -p .verify/infinity-sdk-0.2.1
gh release download sdk-v0.2.1 --repo 777genius/infinity-context \
  --dir .verify/infinity-sdk-0.2.1
test "$(find .verify/infinity-sdk-0.2.1 -maxdepth 1 -type f | wc -l)" -eq 2
gh release verify sdk-v0.2.1 --repo 777genius/infinity-context
gh release verify-asset sdk-v0.2.1 \
  .verify/infinity-sdk-0.2.1/infinity-context-sdk-0.2.1.tgz \
  --repo 777genius/infinity-context
gh release verify-asset sdk-v0.2.1 \
  .verify/infinity-sdk-0.2.1/infinity-context-sdk-release-manifest.json \
  --repo 777genius/infinity-context
```

Pin the immutable release URL in the consumer:

```json
{
  "dependencies": {
    "@infinity-context/sdk": "https://github.com/777genius/infinity-context/releases/download/sdk-v0.2.1/infinity-context-sdk-0.2.1.tgz"
  }
}
```

Then prove a cold, lockfile-driven install:

```bash
test "$(jq -r '.packages["node_modules/@infinity-context/sdk"].resolved' package-lock.json)" = \
  "https://github.com/777genius/infinity-context/releases/download/sdk-v0.2.1/infinity-context-sdk-0.2.1.tgz"
npm ci --ignore-scripts --no-audit --no-fund
node -e 'import("@infinity-context/sdk").then(() => console.log("SDK 0.2.1 import ok"))'
```

Compare the consumer lock integrity and downloaded bytes to the manifest before
installation. A changed tag, tree, lock, workflow, fixture, or tarball requires a new
SDK version.

## Non-recursive verification chain

The pre-upload manifest cannot bind release and asset IDs that do not exist yet
without recursively changing its own asset bytes. After publication or exact-existing
reconciliation, the workflow captures JSON output from release and per-asset
attestation verification. The receipt generator parses those verified statements and
requires the exact annotated-tag commit, repository, tag, release ID, two asset names,
and both SHA-256 digests. Boolean command-line claims are not accepted. It therefore
exclusively creates
`infinity-context-sdk-release-verification-receipt.json`. It records the release ID and
URL, exact asset IDs/digests, the original manifest run ID/attempt, and successful
release/asset verification. Thus reconciliation regenerates the same receipt bytes
for the same exact release even from a later Actions run.
It is uploaded only as a separately named Actions artifact for Discord/operations
custody; it is not a release asset and never changes the exact two-asset policy.

Export the 90-day receipt from the completed run into durable operations custody
before artifact expiry:

```bash
mkdir -p .verify/infinity-sdk-0.2.1/receipt
gh run download <RUN_ID> --repo 777genius/infinity-context \
  --name typescript-sdk-release-verification-sdk-v0.2.1 \
  --dir .verify/infinity-sdk-0.2.1/receipt
test -f .verify/infinity-sdk-0.2.1/receipt/infinity-context-sdk-release-verification-receipt.json
```

Downstream Discord release quality is a separate decision. It binds this immutable
SDK release URL and receipt to the Infinity service/image, embedding/index,
production model/runtime, three 240-meeting outcomes, and two independent reviewer
signatures. None of that evidence belongs in or gates the SDK release manifest.

## Failure and rollback policy

Any draft, duplicated/malformed state, moved tag, unconfirmed rule/immutability
setting, byte drift, extra asset, or failed/malformed attestation stops the workflow.
Drafts remain non-resumable: do not delete, resume, replace, or repair one; investigate
and use a new patch version. A valid published immutable release is recoverable only
through the bounded read-only reconciliation path above. Consumer rollback means
reverting to an earlier already-verified immutable SDK release URL and lockfile,
never rewriting a tag or release.
