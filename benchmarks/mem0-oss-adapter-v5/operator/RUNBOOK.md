# Publishable Mem0 v5 staging bundle

This runbook stages one new, secret-free configuration bundle for the isolated
publishable lane and the exact 2,040-case run. The builder only writes config;
it does not inspect `/proc`, traverse either protected root, contact a provider,
invoke Docker, or create `publishable-run-2040.secrets.json`.

The reviewed template reserves these identities exclusively for this lane:

- Compose project `mem0-v5-publishable-staging-r17-6f2c`;
- loopback host port `29192`;
- Docker socket
  `/run/infinity-context/mem0-v5-publishable-staging-r17-6f2c/docker.sock`;
- bridge accounts `publishable-r17-6f2c-a`, `-b`, and `-c`;
- lane, authority, scheduler, receipt, and attestation paths carrying the
  `r17-6f2c` suffix.

## Fence and public inputs

Capture the account-i/r16 PID, start ticks, boot ID, network-namespace inode,
port, protected host ports, and container IDs through the approved host
inventory. Do not list or read either protected directory. The builder accepts
the observation as data and requires the fence roots to remain exactly:

```text
/var/data/codex-home/live-codex-auth/account-i
/mnt/volume_ams3_1784742570542/infinity-context/live-canaries/mem0-v5-live-d7bf1ac4-r16
```

The three bridge binding values, configuration HMAC, and deployment/server
closure digests and HMACs are public SHA-256 commitments, not keys. Prepare and
review those five bind-mount authority values through the approved offline
authority workflow. The adapter image ID, executable digest, fence identity,
and occupied ports are also public inputs. Never pass a bearer value, API key,
HMAC key, password, or other credential to this builder.

From the repository root, run the builder once with absolute private and public
roots. Repeat each `--account-i-protected-host-port`,
`--account-i-container-id`, and `--bridge-binding-sha256` argument as shown;
also repeat `--occupied-host-port` for every other reserved host port.

```bash
python benchmarks/mem0-oss-adapter-v5/tools/build_publishable_staging.py \
  --template benchmarks/mem0-oss-adapter-v5/operator/publishable-staging.template.json \
  --output-root "$STAGING_PRIVATE_ROOT" \
  --authority-root "$STAGING_PUBLIC_AUTHORITY_ROOT" \
  --adapter-image-id "$REVIEWED_ADAPTER_IMAGE_ID" \
  --codex-executable-sha256 "$REVIEWED_CODEX_EXECUTABLE_SHA256" \
  --bridge-binding-sha256 "$PUBLIC_BRIDGE_BINDING_A_SHA256" \
  --bridge-binding-sha256 "$PUBLIC_BRIDGE_BINDING_B_SHA256" \
  --bridge-binding-sha256 "$PUBLIC_BRIDGE_BINDING_C_SHA256" \
  --config-hmac-sha256 "$PUBLIC_CONFIG_HMAC_SHA256" \
  --deployment-closure-sha256 "$PUBLIC_DEPLOYMENT_CLOSURE_SHA256" \
  --deployment-closure-hmac-sha256 "$PUBLIC_DEPLOYMENT_CLOSURE_HMAC_SHA256" \
  --server-closure-sha256 "$PUBLIC_SERVER_CLOSURE_SHA256" \
  --server-closure-hmac-sha256 "$PUBLIC_SERVER_CLOSURE_HMAC_SHA256" \
  --account-i-pid "$ACCOUNT_I_R16_PID" \
  --account-i-start-ticks "$ACCOUNT_I_R16_START_TICKS" \
  --account-i-boot-id "$ACCOUNT_I_R16_BOOT_ID" \
  --account-i-netns-inode "$ACCOUNT_I_R16_NETNS_INODE" \
  --account-i-port "$ACCOUNT_I_R16_PORT" \
  --account-i-protected-host-port 6334 \
  --account-i-protected-host-port 8891 \
  --account-i-protected-host-port 8892 \
  --account-i-protected-host-port 19091 \
  --account-i-container-id "$ACCOUNT_I_R16_CONTAINER_ID"
```

The command fails if an output already exists, any private directory is not
owned by the current user with mode `0700`, a generated config path collides,
the staging port is internal/protected/occupied, a name is duplicated or
reserved, or the account-i/r16 fence is incomplete. It creates all private
directories as `0700` and both JSON configs as `0600`. An existing secrets path
is a collision and is never read or overwritten.

## Review and provision

Expect the builder's single JSON result to report `STAGED_SECRET_FREE` and five
fully quoted commands. Review both generated configs and confirm that the
secrets path named by `secrets_path_not_created` does not exist. Populate the
authority layout referenced by the lane config using reviewed immutable public
artifacts.

Provision the run secrets file separately through the approved secret channel.
It must use the `memory-comparison-publishable-run-secrets.v1` schema, be a
regular current-user-owned `0600` file below the reported `0700` run private
root, and contain five distinct domain-separated keys plus adapter-private
material. Do not commit, print, or paste that file into an issue or terminal
transcript.

## Exact command order

Use the commands emitted by the builder without editing their paths or flags:

1. `start_create` starts the cached-only lane with fleet mode `create`.
2. `attest_create` proves the created lane with the same fleet mode.
3. `run_2040` is the only command carrying `--allow-live`; run it only after
   the explicit paid-run approval and secret provisioning.
4. After an interruption, use `start_reopen`, then `attest_reopen`, then the
   unchanged `run_2040` command. Do not use `create` for recovery.

Stop on any nonzero result. Never substitute account-i, r16, their paths, their
ports, their container IDs, or their credentials into the new lane.
