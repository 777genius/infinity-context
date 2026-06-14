#!/bin/sh
set -eu

asset_dir="${MEMORY_ASSET_STORAGE_DIR:-/var/lib/memo-stack/assets}"

mkdir -p "$asset_dir"
chown memo:memo /var/lib/memo-stack "$asset_dir" /home/memo

exec gosu memo "$@"
