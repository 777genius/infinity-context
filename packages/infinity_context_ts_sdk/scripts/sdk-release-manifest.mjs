#!/usr/bin/env node
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { lstat, readFile, readdir, realpath, writeFile } from "node:fs/promises";
import { basename, dirname, relative, resolve, sep } from "node:path";
import { parseArgs, promisify } from "node:util";

const execFileAsync = promisify(execFile);
const SCHEMA = "infinity-context-typescript-sdk-release.v1";
const MAX_ARTIFACT_BYTES = 100 * 1024 * 1024;
const MAX_METADATA_BYTES = 10 * 1024 * 1024;
const BUILD_PROFILE = "node24-npm-ci-pack-once.v1";
const MANIFEST_NAME = "infinity-context-sdk-release-manifest.json";

export async function runReleaseManifestCli(argv) {
  const { values } = parseArgs({
    args: argv,
    options: {
      artifact: { type: "string" },
      "artifact-root": { type: "string" },
      "build-profile": { type: "string" },
      manifest: { type: "string" },
      "node-version": { type: "string" },
      output: { type: "string" },
      "output-root": { type: "string" },
      "package-root": { type: "string" },
      repository: { type: "string" },
      "repository-root": { type: "string" },
      tag: { type: "string" },
      "workflow-path": { type: "string" },
      "workflow-run-attempt": { type: "string" },
      "workflow-run-id": { type: "string" },
      "workflow-sha256": { type: "string" },
    },
    strict: true,
    allowPositionals: false,
  });
  const options = await validatedOptions(values);
  const expected = await buildManifest(options);
  if (options.manifest !== undefined) {
    const bytes = await safeRead(options.manifest, options.outputRoot, MAX_METADATA_BYTES, "manifest");
    const parsed = parseCanonicalObject(bytes, "release manifest");
    assertExactObject(parsed, expected, "release manifest");
    return { manifest: parsed, path: options.manifest, verified: true };
  }
  await assertProspectivePath(options.output, options.outputRoot, "output");
  await writeFile(options.output, `${canonicalJson(expected)}\n`, {
    encoding: "utf8", flag: "wx", mode: 0o444,
  });
  return { manifest: expected, path: options.output, verified: false };
}

async function validatedOptions(values) {
  const required = (name) => requiredString(values[name], `--${name}`);
  const repositoryRoot = resolve(required("repository-root"));
  const packageRoot = resolve(required("package-root"));
  const artifactRoot = resolve(required("artifact-root"));
  const outputRoot = resolve(required("output-root"));
  await assertDirectory(repositoryRoot, repositoryRoot, "repository root");
  await assertDirectory(packageRoot, repositoryRoot, "package root");
  await assertDirectory(artifactRoot, repositoryRoot, "artifact root");
  await assertDirectory(outputRoot, repositoryRoot, "output root");
  const artifact = resolve(required("artifact"));
  const outputValue = values.output;
  const manifestValue = values.manifest;
  if ((outputValue === undefined) === (manifestValue === undefined)) {
    throw new Error("exactly one of --output or --manifest is required");
  }
  const output = outputValue === undefined ? undefined : resolve(required("output"));
  const manifest = manifestValue === undefined ? undefined : resolve(required("manifest"));
  const tag = required("tag");
  if (!/^sdk-v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$/u.test(tag)) {
    throw new Error("--tag must use exact sdk-vX.Y.Z form");
  }
  const nodeVersion = required("node-version");
  if (!/^24\.18\.0$/u.test(nodeVersion)) throw new Error("--node-version must be 24.18.0");
  if (required("build-profile") !== BUILD_PROFILE) {
    throw new Error(`--build-profile must be ${BUILD_PROFILE}`);
  }
  const repository = required("repository");
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/u.test(repository)) {
    throw new Error("--repository must be an owner/name identity");
  }
  const workflowPath = required("workflow-path");
  if (workflowPath !== ".github/workflows/typescript-sdk-release.yml") {
    throw new Error("--workflow-path is not the SDK release workflow");
  }
  return {
    artifact, artifactRoot, buildProfile: BUILD_PROFILE, manifest, nodeVersion, output,
    outputRoot, packageRoot, repository, repositoryRoot, tag, workflowPath,
    workflowRunAttempt: positiveIntegerString(required("workflow-run-attempt"), "workflow run attempt"),
    workflowRunId: positiveIntegerString(required("workflow-run-id"), "workflow run id"),
    workflowSha256: hexDigest(required("workflow-sha256"), "workflow SHA-256"),
  };
}

async function buildManifest(options) {
  const packageJsonPath = resolve(options.packageRoot, "package.json");
  const lockPath = resolve(options.packageRoot, "package-lock.json");
  const workflowFile = resolve(options.repositoryRoot, options.workflowPath);
  const [packageBytes, lockBytes, artifactBytes, workflowBytes] = await Promise.all([
    safeRead(packageJsonPath, options.packageRoot, MAX_METADATA_BYTES, "package.json"),
    safeRead(lockPath, options.packageRoot, MAX_METADATA_BYTES, "package-lock.json"),
    safeRead(options.artifact, options.artifactRoot, MAX_ARTIFACT_BYTES, "SDK artifact"),
    safeRead(workflowFile, options.repositoryRoot, MAX_METADATA_BYTES, "release workflow"),
  ]);
  const packageJson = parseObject(packageBytes, "package.json");
  const lock = parseObject(lockBytes, "package-lock.json");
  const packageName = requiredString(packageJson.name, "package name");
  const packageVersion = exactSemver(packageJson.version, "package version");
  if (compareSemver(packageVersion, "0.2.1") < 0) throw new Error("package version must be 0.2.1 or newer");
  if (options.tag !== `sdk-v${packageVersion}`) throw new Error("tag/version drift");
  if (lock.version !== packageVersion || lock.packages?.[""]?.version !== packageVersion) {
    throw new Error("package-lock version drift");
  }
  const artifactName = npmArtifactName(packageName, packageVersion);
  if (basename(options.artifact) !== artifactName) throw new Error(`artifact name must be ${artifactName}`);
  const repositoryUrl = packageRepositoryUrl(packageJson.repository);
  if (repositoryUrl !== `https://github.com/${options.repository}`) throw new Error("repository identity drift");
  if (sha256(workflowBytes) !== options.workflowSha256) throw new Error("workflow blob digest drift");

  const git = await gitIdentity(options.repositoryRoot, options.tag);
  const inventory = await contractFixtureInventory(options.packageRoot);
  const manifest = {
    artifact_byte_length: artifactBytes.byteLength,
    artifact_name: artifactName,
    artifact_sha256_hex: sha256(artifactBytes),
    artifact_sri_sha512: `sha512-${createHash("sha512").update(artifactBytes).digest("base64")}`,
    build_profile: options.buildProfile,
    build_workflow_path: options.workflowPath,
    build_workflow_run_attempt: Number(options.workflowRunAttempt),
    build_workflow_run_id: Number(options.workflowRunId),
    build_workflow_sha256_hex: options.workflowSha256,
    contract_fixture_inventory: inventory,
    contract_fixture_inventory_sha256_hex: sha256(Buffer.from(canonicalJson(inventory))),
    git_object_format: git.objectFormat,
    node_version: options.nodeVersion,
    package_lock_sha256_hex: sha256(lockBytes),
    package_name: packageName,
    package_version: packageVersion,
    release_tag: options.tag,
    repository: options.repository,
    repository_url: repositoryUrl,
    schema_version: SCHEMA,
    source_commit: git.commit,
    source_git_tree_oid: git.tree,
    tag_object_oid: git.tagObject,
  };
  canonicalJson(manifest);
  return manifest;
}

async function gitIdentity(root, tag) {
  const objectFormat = await git(root, "rev-parse", "--show-object-format");
  const pattern = objectFormat === "sha1" ? /^[0-9a-f]{40}$/u
    : objectFormat === "sha256" ? /^[0-9a-f]{64}$/u : null;
  if (pattern === null) throw new Error("unsupported Git object format");
  const commit = await git(root, "rev-parse", "HEAD^{commit}");
  const tree = await git(root, "rev-parse", "HEAD^{tree}");
  const tagObject = await git(root, "rev-parse", `${tag}^{tag}`);
  const tagTarget = await git(root, "rev-parse", `${tag}^{commit}`);
  if (![commit, tree, tagObject, tagTarget].every((oid) => pattern.test(oid))) {
    throw new Error("malformed Git object identity");
  }
  if (tagTarget !== commit) throw new Error("tag target drift");
  return { commit, tree, tagObject, objectFormat };
}

async function contractFixtureInventory(packageRoot) {
  const paths = [];
  await collectFiles(resolve(packageRoot, "src"), packageRoot, paths, (path) => path.endsWith(".ts"));
  await collectFiles(resolve(packageRoot, "fixtures"), packageRoot, paths, (path) => path.endsWith(".json"));
  paths.sort();
  if (paths.length === 0) throw new Error("contract/fixture inventory is empty");
  return Promise.all(paths.map(async (path) => {
    const bytes = await safeRead(resolve(packageRoot, path), packageRoot, MAX_METADATA_BYTES, `inventory ${path}`);
    return { path, sha256_hex: sha256(bytes) };
  }));
}

async function collectFiles(directory, root, paths, include) {
  await assertDirectory(directory, root, "inventory directory");
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const path = resolve(directory, entry.name);
    if (entry.isSymbolicLink()) throw new Error("inventory contains a symlink");
    if (entry.isDirectory()) await collectFiles(path, root, paths, include);
    else if (entry.isFile() && include(path)) paths.push(relative(root, path).split(sep).join("/"));
    else if (!entry.isFile()) throw new Error("inventory contains a non-regular file");
  }
}

async function safeRead(path, allowedRoot, maximumBytes, label) {
  await assertContained(path, allowedRoot, label);
  const status = await lstat(path);
  if (status.isSymbolicLink() || !status.isFile()) throw new Error(`${label} must be a regular non-symlink file`);
  if (status.size > maximumBytes) throw new Error(`${label} exceeds the size limit`);
  return readFile(path);
}

async function assertDirectory(path, allowedRoot, label) {
  await assertContained(path, allowedRoot, label);
  const status = await lstat(path);
  if (status.isSymbolicLink() || !status.isDirectory()) throw new Error(`${label} must be a regular directory`);
}

async function assertContained(path, allowedRoot, label) {
  const [actual, root] = await Promise.all([realpath(path), realpath(allowedRoot)]);
  if (actual !== root && !actual.startsWith(`${root}${sep}`)) throw new Error(`${label} escapes its allowed root`);
}

async function assertProspectivePath(path, allowedRoot, label) {
  const root = await realpath(allowedRoot);
  const parent = await realpath(dirname(path));
  if (parent !== root && !parent.startsWith(`${root}${sep}`)) throw new Error(`${label} escapes its allowed root`);
  if (basename(path) !== MANIFEST_NAME) throw new Error(`output name must be ${MANIFEST_NAME}`);
}

function parseCanonicalObject(bytes, label) {
  const text = bytes.toString("utf8");
  const value = parseObject(bytes, label);
  const canonical = canonicalJson(value);
  if (text !== canonical && text !== `${canonical}\n`) {
    throw new Error(`${label} must be canonical JSON without duplicate keys`);
  }
  return value;
}

function parseObject(bytes, label) {
  let value;
  try { value = JSON.parse(bytes.toString("utf8")); }
  catch (error) { throw new Error(`${label} is not valid JSON`, { cause: error }); }
  if (value === null || Array.isArray(value) || typeof value !== "object") {
    throw new Error(`${label} must be a JSON object`);
  }
  return value;
}

function assertExactObject(actual, expected, label) {
  if (canonicalJson(actual) !== canonicalJson(expected)) throw new Error(`${label} semantic binding drift`);
}

function canonicalJson(value) {
  if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) throw new Error("canonical JSON rejects unsafe numbers");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
  }
  throw new Error("canonical JSON contains an unsupported value");
}

function requiredString(value, label) {
  if (typeof value !== "string" || value.trim() === "" || /[\r\n]/u.test(value)) {
    throw new Error(`${label} must be a non-empty single-line string`);
  }
  return value;
}

function exactSemver(value, label) {
  const version = requiredString(value, label);
  if (!/^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$/u.test(version)) {
    throw new Error(`${label} must be exact stable SemVer`);
  }
  return version;
}

function compareSemver(left, right) {
  const a = left.split(".").map(Number); const b = right.split(".").map(Number);
  for (let index = 0; index < 3; index += 1) {
    if (a[index] !== b[index]) return a[index] < b[index] ? -1 : 1;
  }
  return 0;
}

function positiveIntegerString(value, label) {
  if (!/^[1-9]\d*$/u.test(value) || !Number.isSafeInteger(Number(value))) {
    throw new Error(`${label} must be a positive safe integer`);
  }
  return value;
}

function hexDigest(value, label) {
  if (!/^[0-9a-f]{64}$/u.test(value)) throw new Error(`${label} must be lowercase SHA-256 hex`);
  return value;
}

function npmArtifactName(name, version) {
  const normalized = name.startsWith("@") ? name.slice(1).replace("/", "-") : name;
  if (!/^[a-z0-9][a-z0-9._-]*$/u.test(normalized)) throw new Error("unsafe npm package name");
  return `${normalized}-${version}.tgz`;
}

function packageRepositoryUrl(repository) {
  const raw = typeof repository === "string" ? repository : repository?.url;
  return requiredString(raw, "repository URL").replace(/^git\+https:\/\//u, "https://").replace(/\.git$/u, "");
}

function sha256(bytes) { return createHash("sha256").update(bytes).digest("hex"); }

async function git(root, ...args) {
  const { stdout } = await execFileAsync("git", ["-C", root, ...args], { encoding: "utf8" });
  return stdout.trim();
}

if (process.argv[1] !== undefined && resolve(process.argv[1]) === resolve(new URL(import.meta.url).pathname)) {
  const result = await runReleaseManifestCli(process.argv.slice(2));
  process.stdout.write(`${result.verified ? "verified" : "created"}=${result.path}\n`);
}
