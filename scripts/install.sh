#!/usr/bin/env bash
set -euo pipefail

PREFIX="${INFINITY_CONTEXT_HOME:-${HOME}/.infinity-context}"
REPO_URL="${INFINITY_CONTEXT_INSTALL_REPO:-https://github.com/777genius/infinity-context.git}"
REF="${INFINITY_CONTEXT_INSTALL_REF:-v0.1.0}"
NO_START=0
DRY_RUN=0
FORCE=0
RESET=0
RESET_DATA=0
OPEN_UI=1
ALL_AGENTS=0
AGENT_TOOLS=1
RETRIEVE_ONLY=0
MANUAL_MEMORY=0
AGENTS=()

PLUGIN_KIT_AI_VERSION="1.2.4"
PLUGIN_KIT_AI_RELEASE_URL="https://github.com/777genius/plugin-kit-ai/releases/download/v${PLUGIN_KIT_AI_VERSION}"
BOOTSTRAP_PIP_VERSION="26.2.1"
BOOTSTRAP_SETUPTOOLS_VERSION="83.0.0"
BOOTSTRAP_WHEEL_VERSION="0.47.0"

usage() {
  cat <<'USAGE'
Infinity Context local installer.

Usage:
  scripts/install.sh [options]

Options:
  --dry-run             Print actions without writing files.
  --prefix PATH         Install home. Defaults to ~/.infinity-context.
  --repo URL_OR_PATH    Git repo URL or local path.
  --ref REF             Git ref to checkout. Defaults to v0.1.0.
  --no-start            Install files only, do not start Docker stack.
  --force               Overwrite generated config files.
  --reset               Stop existing containers before install. Keeps data volumes.
  --reset-data          With --reset, remove compose volumes too.
  --agent AGENT         Agent to connect. Repeat for multiple agents.
  --all-agents          Connect every supported agent.
  --no-agent-tools      Do not install plugin-kit-ai or modify agent configuration.
  --open-ui             Open the local memory browser after setup (default).
  --no-open-ui          Do not open the local memory browser.
  --retrieve-only       Start with memory retrieval only; do not capture new memory.
  --manual-memory       Require explicit manual memory capture.
  -h, --help            Show help.
USAGE
}

log() {
  printf '%s\n' "infinity-context install: $*" >&2
}

run() {
  if [ "${DRY_RUN}" = "1" ]; then
    printf 'dry-run:'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --dry-run)
        DRY_RUN=1
        ;;
      --prefix)
        shift
        PREFIX="${1:?--prefix requires a path}"
        ;;
      --repo)
        shift
        REPO_URL="${1:?--repo requires a URL or path}"
        ;;
      --ref)
        shift
        REF="${1:?--ref requires a git ref}"
        ;;
      --no-start)
        NO_START=1
        ;;
      --force)
        FORCE=1
        ;;
      --reset)
        RESET=1
        ;;
      --reset-data)
        RESET_DATA=1
        ;;
      --agent)
        shift
        AGENTS+=("${1:?--agent requires an agent name}")
        ;;
      --all-agents)
        ALL_AGENTS=1
        ;;
      --no-agent-tools)
        AGENT_TOOLS=0
        ;;
      --open-ui)
        OPEN_UI=1
        ;;
      --no-open-ui)
        OPEN_UI=0
        ;;
      --retrieve-only)
        RETRIEVE_ONLY=1
        ;;
      --manual-memory)
        MANUAL_MEMORY=1
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        log "unknown argument: $1"
        usage >&2
        exit 2
        ;;
    esac
    shift
  done

  if [ "${ALL_AGENTS}" = "1" ] && [ "${#AGENTS[@]}" -gt 0 ]; then
    log "--all-agents cannot be combined with --agent"
    exit 2
  fi
  if [ "${RETRIEVE_ONLY}" = "1" ] && [ "${MANUAL_MEMORY}" = "1" ]; then
    log "--retrieve-only cannot be combined with --manual-memory"
    exit 2
  fi
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "required command missing: $1"
    exit 127
  fi
}

require_docker_compose() {
  if ! docker compose version >/dev/null 2>&1; then
    log "docker compose is unavailable"
    exit 127
  fi
}

require_supported_python() {
  if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    log "Python 3.11 or newer is required"
    exit 2
  fi
}

require_checksum_command() {
  if command -v sha256sum >/dev/null 2>&1 || command -v shasum >/dev/null 2>&1; then
    return 0
  fi
  log "required checksum command missing: sha256sum or shasum"
  exit 127
}

prepare_dirs() {
  run mkdir -p "${PREFIX}/bin" "${PREFIX}/logs" "${PREFIX}/run"
}

clone_or_update_repo() {
  local src_dir="${PREFIX}/src"
  if [ ! -d "${src_dir}/.git" ]; then
    if [ -e "${src_dir}" ]; then
      log "${src_dir} exists but is not a git checkout"
      exit 1
    fi
    run git clone --depth 1 --branch "${REF}" "${REPO_URL}" "${src_dir}"
    return 0
  fi
  if [ -n "$(git -C "${src_dir}" status --porcelain)" ]; then
    log "${src_dir} has local changes; refusing to overwrite the managed checkout"
    log "use a new --prefix or resolve those changes before updating"
    exit 1
  fi
  run git -C "${src_dir}" fetch --tags --prune origin
  if git -C "${src_dir}" show-ref --verify --quiet "refs/tags/${REF}"; then
    run git -C "${src_dir}" checkout --detach "refs/tags/${REF}"
  elif git -C "${src_dir}" show-ref --verify --quiet "refs/remotes/origin/${REF}"; then
    run git -C "${src_dir}" checkout --detach "refs/remotes/origin/${REF}"
  else
    run git -C "${src_dir}" checkout --detach "${REF}"
  fi
}

install_python_runtime() {
  local src_dir="${PREFIX}/src"
  local python_bin="${src_dir}/.venv/bin/python"
  if [ ! -x "${python_bin}" ]; then
    run python3 -m venv "${src_dir}/.venv"
  fi
  run "${python_bin}" -m pip install --disable-pip-version-check --upgrade \
    "pip==${BOOTSTRAP_PIP_VERSION}" \
    "setuptools==${BOOTSTRAP_SETUPTOOLS_VERSION}" \
    "wheel==${BOOTSTRAP_WHEEL_VERSION}"
  run "${python_bin}" -m pip install --disable-pip-version-check --upgrade \
    "${src_dir}[mcp]"
}

reset_runtime_if_requested() {
  if [ "${RESET}" != "1" ]; then
    return 0
  fi
  local src_dir="${PREFIX}/src"
  if [ ! -f "${src_dir}/docker-compose.yml" ]; then
    return 0
  fi
  if [ "${RESET_DATA}" = "1" ]; then
    run docker compose --project-directory "${src_dir}" --profile lite --profile full down -v
  else
    run docker compose --project-directory "${src_dir}" --profile lite --profile full down
  fi
}

install_cli_shim() {
  local shim="${PREFIX}/bin/infinity-context"
  local src_dir="${PREFIX}/src"
  if [ "${DRY_RUN}" = "1" ]; then
    log "would write ${shim}"
    return 0
  fi
  cat >"${shim}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
repo_root="${src_dir}"
python_bin="\${repo_root}/.venv/bin/python"
if [ ! -x "\${python_bin}" ]; then
  if command -v python3 >/dev/null 2>&1; then
    python_bin="\$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    python_bin="\$(command -v python)"
  else
    printf '%s\n' "infinity-context: python not found" >&2
    exit 127
  fi
fi
export INFINITY_CONTEXT_HOME="${PREFIX}"
export INFINITY_CONTEXT_REPO_ROOT="\${repo_root}"
export PATH="${PREFIX}/bin:\${PATH}"
infinity_context_pythonpath="\${repo_root}/packages/infinity_context_core:\${repo_root}/packages/infinity_context_server:\${repo_root}/packages/infinity_context_runtime_bridge:\${repo_root}/packages/infinity_context_adapters:\${repo_root}/packages/infinity_context_contracts:\${repo_root}/packages/infinity_context_sdk:\${repo_root}/packages/infinity_context_obsidian:\${repo_root}/packages/infinity_context_mcp:\${repo_root}/packages/infinity_context_cli"
if [ -n "\${PYTHONPATH:-}" ]; then
  export PYTHONPATH="\${infinity_context_pythonpath}:\${PYTHONPATH}"
else
  export PYTHONPATH="\${infinity_context_pythonpath}"
fi
exec "\${python_bin}" -m infinity_context_cli "\$@"
EOF
  chmod +x "${shim}"
}

plugin_kit_platform() {
  local os
  local arch
  case "$(uname -s)" in
    Darwin)
      os="darwin"
      ;;
    Linux)
      os="linux"
      ;;
    MINGW*|MSYS*|CYGWIN*)
      os="windows"
      ;;
    *)
      log "plugin-kit-ai is unsupported on $(uname -s)"
      exit 1
      ;;
  esac
  case "$(uname -m)" in
    x86_64|amd64)
      arch="amd64"
      ;;
    arm64|aarch64)
      arch="arm64"
      ;;
    *)
      log "plugin-kit-ai is unsupported on $(uname -m)"
      exit 1
      ;;
  esac
  printf '%s_%s\n' "${os}" "${arch}"
}

plugin_kit_checksum() {
  case "$1" in
    darwin_amd64)
      printf '%s\n' 'f914226c7ebf8930e751e14da58bc4cd23eeaad4cc7f10fc31629a8233c7c6dc'
      ;;
    darwin_arm64)
      printf '%s\n' '6812086dec43958508efb2945afd06c1b1ec0b7eac8ba0119790e06a9fed8bb1'
      ;;
    linux_amd64)
      printf '%s\n' 'fd06f16292ffcc34f5436923e59039930668e5bbfb07e82ef589cf9d3b39822a'
      ;;
    linux_arm64)
      printf '%s\n' '46dcb07cd7d7a39fcc095ab3a38270bcdb5e524dad149fbc9d381396f163815b'
      ;;
    windows_amd64)
      printf '%s\n' '446ca76bec7eac018bca577f21139167dc5ebdd7fad968e90ffea40f5cfec707'
      ;;
    windows_arm64)
      printf '%s\n' 'b6eb8f25b14884bce1d7f8489e1a7f87ca98a82a6a0da5c51d85fc44ecbafd87'
      ;;
    *)
      return 1
      ;;
  esac
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

cleanup_plugin_kit_temp() {
  if [ -n "${PLUGIN_KIT_TEMP_DIR:-}" ] && [ -d "${PLUGIN_KIT_TEMP_DIR}" ]; then
    case "${PLUGIN_KIT_TEMP_DIR}" in
      /tmp/*|/var/folders/*)
        rm -rf "${PLUGIN_KIT_TEMP_DIR}"
        ;;
    esac
  fi
}

install_plugin_kit_ai() {
  if [ "${AGENT_TOOLS}" != "1" ] || [ "${NO_START}" = "1" ]; then
    return 0
  fi
  local platform
  local expected_checksum
  local asset_name
  local archive_path
  local binary_name
  local extracted_binary
  local actual_checksum
  platform="$(plugin_kit_platform)"
  expected_checksum="$(plugin_kit_checksum "${platform}")" || {
    log "missing pinned checksum for plugin-kit-ai ${platform}"
    exit 1
  }
  asset_name="plugin-kit-ai_${PLUGIN_KIT_AI_VERSION}_${platform}.tar.gz"
  if [ "${platform#windows_}" != "${platform}" ]; then
    binary_name="plugin-kit-ai.exe"
  else
    binary_name="plugin-kit-ai"
  fi
  if [ "${DRY_RUN}" = "1" ]; then
    log "would install verified plugin-kit-ai ${PLUGIN_KIT_AI_VERSION} (${platform}) into ${PREFIX}/bin"
    return 0
  fi
  require_command curl
  require_command tar
  require_checksum_command
  PLUGIN_KIT_TEMP_DIR="$(mktemp -d)"
  trap cleanup_plugin_kit_temp EXIT
  archive_path="${PLUGIN_KIT_TEMP_DIR}/${asset_name}"
  run curl --fail --location --proto '=https' --tlsv1.2 --retry 3 --output "${archive_path}" "${PLUGIN_KIT_AI_RELEASE_URL}/${asset_name}"
  actual_checksum="$(sha256_file "${archive_path}")"
  if [ "${actual_checksum}" != "${expected_checksum}" ]; then
    log "plugin-kit-ai checksum verification failed"
    exit 1
  fi
  run tar -xzf "${archive_path}" -C "${PLUGIN_KIT_TEMP_DIR}"
  extracted_binary="${PLUGIN_KIT_TEMP_DIR}/${binary_name}"
  if [ ! -f "${extracted_binary}" ]; then
    log "plugin-kit-ai archive did not contain ${binary_name}"
    exit 1
  fi
  run chmod 0755 "${extracted_binary}"
  run mv "${extracted_binary}" "${PREFIX}/bin/${binary_name}"
  log "installed verified plugin-kit-ai ${PLUGIN_KIT_AI_VERSION}"
}

start_if_requested() {
  local src_dir="${PREFIX}/src"
  local quickstart_args=(quickstart --home "${PREFIX}" --repo-dir "${src_dir}" --lite)
  if [ "${ALL_AGENTS}" = "1" ]; then
    quickstart_args+=(--all-agents)
  else
    if [ "${#AGENTS[@]}" -eq 0 ]; then
      quickstart_args+=(--agent codex)
    else
      local agent
      for agent in "${AGENTS[@]}"; do
        quickstart_args+=(--agent "${agent}")
      done
    fi
  fi
  if [ "${FORCE}" = "1" ]; then
    quickstart_args+=(--force)
  fi
  if [ "${RETRIEVE_ONLY}" = "1" ]; then
    quickstart_args+=(--retrieve-only)
  elif [ "${MANUAL_MEMORY}" = "1" ]; then
    quickstart_args+=(--manual-memory)
  fi
  if [ "${NO_START}" = "1" ]; then
    quickstart_args+=(--no-start --no-install-agents --no-open-ui)
  else
    if [ "${AGENT_TOOLS}" != "1" ]; then
      quickstart_args+=(--no-install-agents)
    fi
    if [ "${OPEN_UI}" = "1" ]; then
      quickstart_args+=(--open-ui)
    else
      quickstart_args+=(--no-open-ui)
    fi
  fi
  run "${PREFIX}/bin/infinity-context" "${quickstart_args[@]}"
}

print_next_steps() {
  cat <<EOF
Infinity Context installed.

Next:
  export PATH="${PREFIX}/bin:\$PATH"
  infinity-context status
  infinity-context digest "current architecture decisions" --space default --memory_scope default
EOF
}

main() {
  parse_args "$@"
  require_command bash
  require_command git
  require_command python3
  require_supported_python
  if [ "${NO_START}" != "1" ] || [ "${RESET}" = "1" ]; then
    require_command docker
    require_docker_compose
  fi
  prepare_dirs
  clone_or_update_repo
  install_python_runtime
  reset_runtime_if_requested
  install_cli_shim
  install_plugin_kit_ai
  start_if_requested
  print_next_steps
}

main "$@"
