# Publishable Mem0 v5 staging bundle

This runbook stages one new, secret-free configuration bundle for the isolated
publishable lane and the exact 2,040-case run. The builder only writes config;
it does not inspect `/proc`, traverse either protected root, contact a provider,
invoke Docker, or create `publishable-run-2040.secrets.json`.

The reviewed template reserves these identities exclusively for this lane:

- Compose project `mem0-v5-publishable-staging-r17-6f2c`;
- loopback host port `29192`;
- bridge accounts `publishable-r17-6f2c-a`, `-b`, and `-c`;
- lane, authority, scheduler, receipt, and attestation paths carrying the
  `r17-6f2c` suffix.

It also pins Docker authority to the benchmark-isolated daemon at
`unix:///run/infinity-locomo-docker/docker.sock`. The exact URI is covered by
the generated lane config's configuration HMAC, supplied through the runner's
clean environment, and passed to Docker with an explicit `--host`. Ambient
`DOCKER_HOST` is not authoritative. The exact Compose project name remains the
resource-isolation boundary on that daemon.

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

Expect the builder's single JSON result to report `STAGED_SECRET_FREE`, four
fully quoted commands, and an explicit `operator_order` list. Review both generated configs and confirm that the
secrets path named by `secrets_path_not_created` does not exist. Populate the
authority layout referenced by the lane config using reviewed immutable public
artifacts.

The run config's adapter object is the exact seven-section production provider
contract. Its reviewed runtime pin, source-commit digest, source manifest,
runtime authority, lane receipt directory, and loopback endpoint must remain
unchanged between review and execution. The suite's 64-character source-commit
authority is exactly SHA-256 over the lowercase 40-character Git commit SHA-1
ASCII exposed by that runtime pin; the provider authenticates this mapping
against the signed adapter response.

The Codex executable ceiling is a local anti-DoS verification budget, not an
executable-format or provider protocol requirement. The production verifier's
`CODEX_EXECUTABLE_MAX_BYTES` contract accepts at most 335,544,320 bytes
(320 MiB), hashes the opened file in bounded chunks, and still requires the
result to match the exact reviewed SHA-256 value supplied to the staging
builder. The builder deliberately does not open or hash the executable itself.

Provision the run secrets file separately through the approved secret channel.
It must use the `memory-comparison-publishable-run-secrets.v1` schema, be a
regular current-user-owned `0600` file below the reported `0700` run private
root, and contain five distinct domain-separated keys plus adapter-private
material. Do not commit, print, or paste that file into an issue or terminal
transcript.

The adapter-private material must include the distinct runtime-attestation root
used by the adapter's `/v5/runtime/attest` challenge. It must match the lane's
`runtime-attestation-secret` file and must not be reused as a bridge receipt,
launcher, journal, extraction, retrieval, output, or publication key. The run
provider authenticates a fresh challenge response and the exact create/reopen
host receipt before it opens extraction, official cases, retrieval, or a live
session.

## Exact command order

Use the commands emitted by the builder without editing their paths or flags:

1. Run `acceptance` once on fresh staged state. It owns the complete
   provider-free lifecycle: exact-project empty gate, cached-only
   `create`, immutable runtime and source-attestation readback, controlled stop
   with bind-state identity preservation, cached-only `reopen`, second
   attestation, and exact-project teardown in `finally`. It then verifies zero
   exact-project containers, networks, and volumes. It never runs Docker prune,
   removes another project, builds, pulls, or calls a provider.
2. `start_reopen` starts the accepted bind-backed state with fleet mode
   `reopen`. Acceptance has already initialized that state, so do not use
   `create` afterward.
3. `attest_reopen` proves the reopened paid-run lane before dispatch.
4. `run_2040` is the only command carrying `--allow-live`; run it only after
   explicit paid-run approval and secret provisioning. After an interruption,
   repeat `start_reopen`, `attest_reopen`, and the unchanged `run_2040` command.

Stop on any nonzero result. Never substitute account-i, r16, their paths, their
ports, their container IDs, or their credentials into the new lane.
Run only one acceptance invocation for a project at a time, with no concurrent
Docker mutation of that project.

The acceptance result is `ACCEPTED_PROVIDER_FREE` only when the fixed command
performs no provider-dispatch operation, both authenticated
`/v5/runtime/attest` probes verify their HMAC and exact `provider_calls: 0`
contract, and the attested startup readiness remains provider-free. This scope
is the acceptance command itself. The lane has no historical or concurrent
provider-call counter, so the result reports that broader counter as
`NOT_AVAILABLE` instead of inventing one. The result also records immutable
host-attestation commitments and the final zero-resource inventory.

Record `acceptance_driver.package_closure_sha256` with the acceptance result.
It is a path-independent digest of the installed `publishable_mem0_v5` package,
which must match the configured deployment copy before mutation and again
before the report is written. `deployment_authority` separately records the
existing authenticated full deployment closure (including its HMAC) and the
instance-specific deployment-input commitment. `adapter_source_commit_sha1`
and `adapter_source_tree_sha1` identify the deployed adapter, not this driver.
The installed package does not contain an authoritative Git revision, so
`acceptance_driver.git_commit.status` is honestly
`NOT_EMBEDDED_IN_INSTALLED_ARTIFACT`; do not substitute ambient Git metadata.

Authenticated empty-state proof is deliberately reported as
`NOT_RUN_REQUIRES_AUTHORITATIVE_RUN_ADMISSION`. The clean-state endpoint is a
one-shot, run-bound capability that requires the official admission,
credential binding, authority, and complete scope inventory. Inventing those
values here would mutate and contaminate the accepted state; the official run
must compose and persist that proof at its pre-dispatch boundary.
