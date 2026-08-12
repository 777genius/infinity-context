# Publishable Mem0 v5 staging bundle

This runbook stages one new, secret-free configuration bundle for the isolated
publishable lane and the exact 2,040-case run. The builder only writes config;
it does not inspect `/proc`, traverse either protected root, contact a provider,
invoke Docker, or create the run secrets, input-provider config, or
input-provider secrets documents.

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
resource-isolation boundary on that daemon. The emitted acceptance command
repeats both reviewed values as exact CLI authorities and selects
`--inventory-scope project`; any cross-wire with the authenticated lane config
fails before Docker mutation.

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
or input-provider document path is a collision and is never read or overwritten.

## Review and provision

Expect the builder's single JSON result to report `STAGED_SECRET_FREE`, the five
fully quoted commands, and explicit `initial_paid_create_order` and
`crash_reopen_resume_order` lists. `operator_order` is the same initial paid
order retained for compatibility. It also reports the separately authorized
`fresh_canary` command. Review all generated configs and confirm
that `secrets_path_not_created`, `input_provider_config_path_not_created`, and
`input_provider_secrets_path_not_created` do not exist. Confirm the reported
`fresh_canary_secrets_path_not_created` does not exist either.
Populate the authority layout referenced by the lane config using reviewed
immutable public artifacts.

The run config's adapter object is the exact seven-section production provider
contract. Its reviewed runtime pin, source-commit digest, source manifest,
runtime authority, lane receipt directory, and loopback endpoint must remain
unchanged between review and execution. The one tracked runtime/source tuple for
this staging generation is:

```text
runtime-pin.json SHA-256    6976b4507071d95bc0df1cb91c56d5c5932fbc5ed1a76475126be05f91e8a15c
source manifest SHA-256     83cd1a1f081cd0c8e1f5f270577061ab18f8927aacd16b7554fd3e750c062a4c
source commit SHA-1         cf7ed782226118cec3eb520e322ebe024c2f332e
SHA-256(commit SHA-1 ASCII) 16c40bb404f71f22d7c5a569b084dcb110a9b01164909261aa0b403ac34c27da
```

The template loader, builder revalidation, and generated lane-config loader all
reject a stale pin or a source digest from another generation before any live
command. The suite's 64-character source-commit authority is exactly SHA-256
over the lowercase 40-character Git commit SHA-1 ASCII exposed by that runtime
pin; the provider authenticates this mapping against the signed adapter
response.

For immutable restaging, use a fresh output root and a fresh public authority
root. Copy (do not symlink or hard-link) the tracked
`benchmarks/mem0-oss-adapter-v5/authority/runtime-pin.json` bytes to the runtime
pin name emitted in the run config, and stage the matching tracked manifest and
64-byte `manifest.sha256`. Before provisioning secrets, independently confirm
the runtime-pin file hash above, its `source_a.commit_sha1` and
`source_a.manifest_sha256`, the manifest file hash, and the no-newline ASCII
commit digest. Make public authority files root-owned or current-operator-owned,
single-link regular files with an admitted read-only mode (`0400`, `0440`, or
`0444`). At run
preflight the immutable reader uses a no-follow stable open, verifies identity,
mode, link count, bounded size, and the configured raw-byte hash, then verifies
the pin's manifest and commit mapping again. A new config HMAC and closure
commitments must cover the restaged paths and tuple through the approved
offline authority workflow; staging does not create an authority receipt or
live evidence.

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

Provision the exact input-provider config and secrets at the two separately
reported paths through the approved private channels. Both must be distinct
regular current-user-owned `0600` files below the same run private root and
must remain distinct from the run config, run secrets, scheduler state, and
sealed input paths. The config uses
`publishable-mem0-infinity-input-preparation.v1`; the secrets use
`publishable-mem0-infinity-input-preparation-secrets.v1`. Supply the reviewed
strict request, receipt, keyring, receipt-key, registration-DSN, live-config,
timeout, and token-ceiling values without editing the emitted command. Use
input-provider fleet mode `create` for fresh preparation or `resume` only for
an admitted preparation recovery; these values are not the Docker lane's
required `reopen` mode. The secrets document carries the Infinity authorization
token and six role-separated HMAC keys. Do not reuse them with each other or
with any run-secret role. The staging builder deliberately does not synthesize,
read, or validate either private document.

For the fresh 1+4 canary, provision the separately reported fresh-canary
secrets file with the normal five outer run keys and the exact
`publishable-mem0-infinity-fresh-chain-provider-secrets.v1` adapter envelope.
Its `fresh_chain` object contains a distinct `one_shot_hmac_key_hex` and the
Infinity bearer used only by the provider-free one-case retrieval preparer;
its `run_provider` object contains the reviewed run-provider secrets. All key
and bearer roles must be distinct. The file must be current-user-owned `0600`
under the reported `0700` private root. Readiness still requires successful
`start_reopen` and `attest_reopen` before this command.

The nested project declares the repository's Core, Server, and Adapters source
roots explicitly for pytest. From the repository root, reproduce the provider
boundary collection without resolving or changing dependencies:

```bash
uv run --directory benchmarks/mem0-oss-adapter-v5 --frozen pytest --collect-only \
  tests/test_package_import_boundary.py \
  tests/test_publishable_input_provider.py \
  tests/test_publishable_provider_attestation.py \
  tests/test_publishable_run_provider_http.py \
  tests/test_publishable_run_provider_preflight.py \
  tests/test_composition_provider_free.py
```

The adapter-private material must include the distinct runtime-attestation root
used by the adapter's `/v5/runtime/attest` challenge. It must match the lane's
`runtime-attestation-secret` file and must not be reused as a bridge receipt,
launcher, journal, extraction, retrieval, output, or publication key. The run
provider authenticates a fresh challenge response and the exact create/reopen
host receipt before it opens extraction, official cases, retrieval, or a live
session.

The generated provider authority sets `required_fleet_mode` to `reopen`.
That lowercase Docker fleet mode is independent of the outer scheduler mode.
Acceptance has already initialized the bind-backed bridge state, so the first
paid run uses fleet `reopen` while the empty scheduler roots select scheduler
`CREATE`. A nonterminal crash leaves the scheduler roots present; the same run
command then selects scheduler `RESUME`, again against a newly attested fleet
`reopen` generation.

## Exact command order

Use the commands emitted by the builder without editing their paths or flags:

The explicitly test-only fresh canary does not run `prepare_inputs` and never
prepares the 2,040-case authority. After `start_reopen` and `attest_reopen`, run
the emitted command exactly:

```text
infinity-context-publishable-fresh-chain-canary --private-root <reported-run-root> --config <reported-fresh-config> --secrets <reported-fresh-secrets> --allow-live-1-plus-4
```

Before the one extraction and four evaluation calls, that command creates or
authenticates a separate sealed retrieval authority containing exactly two
structural groups for `conv-26:qa:1`: the genuine Infinity result and an empty
Mem0 pairing row. This preparation makes no subscription-runtime or Mem0
provider call. The result remains `publishable=false` activation evidence. On
any post-extraction failure it durably aborts, deletes the fresh namespace, and
terminal replay performs no provider calls.

Initial paid scheduler `CREATE` uses `initial_paid_create_order`:

1. Run `acceptance` once on fresh staged state. It owns the complete
   provider-free lifecycle: exact-project empty gate, cached-only
   `create`, immutable runtime and source-attestation readback, controlled stop
   with bind-state identity preservation, cached-only `reopen`, second
   attestation, and exact-project teardown in `finally`. It then verifies zero
   exact-project containers, networks, and volumes. It never runs Docker prune,
   removes another project, builds, pulls, or calls a provider. The reviewed
   command explicitly selects project-scoped inventory, so it neither requests
   daemon-global container inventory nor reads host `/proc` or process
   identities. The stricter global inventory scope remains the command's
   default for environments where those host-wide observations are allowed.
2. `start_reopen` starts the accepted bind-backed state as the first paid fleet
   generation. Acceptance has already initialized that state, so fleet
   `create` is invalid afterward.
3. `attest_reopen` writes the exact current paid fleet receipt before dispatch.
4. `prepare_inputs` invokes the installed
   `infinity-context-publishable-inputs` entrypoint with the unchanged run
   config and run secrets, the exact separately provisioned input-provider
   config and secrets, the 130,226-step ceiling, and explicit
   `--allow-subscription-dispatch`. This is paid provider work, not part of the
   provider-free Docker acceptance. It creates and HMAC-seals both extraction
   terminals and the authenticated retrieval authority consumed by the run.
   Continue only after exit status `0` and JSON `complete: true`.
5. `run_2040` is the only command carrying `--allow-live`; run it only after
   explicit paid-run approval and secret provisioning. With empty scheduler
   roots, this invocation opens scheduler `CREATE`.

Input preparation is resumable and has a required LoCoMo-to-LongMemEval runtime
boundary. Exit status `3` is an authenticated incomplete result, not permission
to continue to `run_2040`: stop the command chain, perform the exact approved
`operator_action` reported by the CLI, reopen the required runtime, and rerun
the unchanged `prepare_inputs` command. Treat any other nonzero status as a
failure. Never invoke `run_2040` merely because terminal path names exist; only
the successful preparation result proves both terminals and retrieval authority
were sealed and read back.

After a nonterminal interruption, use `crash_reopen_resume_order`: run the same
`start_reopen`, `attest_reopen`, and unchanged `run_2040` commands. The new host
receipt must match the current bridge generation, controller/process PIDs, and
container identities; the existing scheduler roots make the last command open
scheduler `RESUME`. This list intentionally does not repeat `prepare_inputs`:
the paid scheduler is never created until preparation has completed. An
interruption during input preparation uses the preparation procedure above,
not the scheduler crash-reopen list.

Except for the explicitly handled `prepare_inputs` status `3`, stop on any
nonzero result. Never substitute account-i, r16, their paths, their ports, their
container IDs, or their credentials into the new lane.
Run only one acceptance invocation for a project at a time, with no concurrent
Docker mutation of that project.

The acceptance result is `ACCEPTED_PROVIDER_FREE` only when the fixed command
performs no provider-dispatch operation, both authenticated
`/v5/runtime/attest` probes verify their HMAC and exact `provider_calls: 0`
contract, and the attested startup readiness remains provider-free. This scope
is the acceptance command itself. The lane has no historical or concurrent
provider-call counter, so the result reports that broader counter as
`NOT_AVAILABLE` instead of inventing one. Project-scoped acceptance records
only exact-project Docker evidence and the final zero-resource inventory; it
does not claim daemon-global container or host-process evidence. Global scope
retains the stricter host-attestation commitments where those observations are
permitted. The project receipt likewise does not infer an active generation or
launch mode from PID-bearing bridge receipts that it deliberately never opens.
It records the mode independently enforced in the exact container environment,
opaque lifecycle-metadata commitments, and a required metadata change across
create/reopen without presenting directory order as authenticated lifecycle
identity.

The lane evidence directory is append-only across these phases. It retains
content-addressed `runtime-attestation-*`, `provider-attestation-*`, and
`docker-acceptance-*` files. Paid preflight snapshots the complete directory,
HMAC-authenticates the exact runtime filename namespace, and selects only the
unique fresh receipt whose project, required fleet mode, and complete fleet
identity match the live authenticated controls. Historical acceptance and paid
generations remain audit evidence; they are never treated as the current paid
generation, and unrelated or stale receipts cannot make preflight pass.

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

## Extraction dispatch recovery

An adapter response with detail
`dispatch_recovery_operator_action_required` means the authenticated state
proves that the physical provider call was claimed, but no exact verified
result is durable. Do not replay `run_2040`, the operation dispatch request, or
the provider completion. The pinned e904 route has no authenticated status API
that can reconstruct the missing output, and its receipt alone is not the
output authority.

The outer input-preparation CLI surfaces the same stop condition as reason code
`publishable_input_extraction_recovery_operator_action_required` and operator
action `stop-retain-private-state-and-escalate-manual-receipt-reconciliation`.

Stop the run, retain the private SQLite database, result directory, scheduler
journal, and provider receipts for audit, then invoke only the run's
authenticated abort/cleanup procedure using its already-bound operation
inventory. Escalate for manual receipt reconciliation before starting a new
run. Never edit the state bit, copy another operation's result, treat a 404 as
provider absence, or synthesize an empty extraction result.

Normal automated reopen is narrower than manual replay: the full-extraction
worker first performs read-only status and may then issue one explicit
operation-bound recovery probe. The adapter authenticates its durable state
before that probe can reach the provider. A proven pre-call absence permits the
single original call, a durable result is returned without a call, and a
claimed operation without a result returns the operator-action error above.
Authenticated schema-v2 `DISPATCHED` rows migrate as claimed/ambiguous; they
never acquire a fabricated pre-call-absence proof.
