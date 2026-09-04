#!/usr/bin/env node
import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { chmod, lstat, mkdir, readFile, readdir, realpath, writeFile } from "node:fs/promises";
import { dirname, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const identityRelativePath = "dist/sdk-artifact-identity.json";

export async function createSdkArtifactIdentity({
  root = packageRoot,
  sourceCommit = process.env.INFINITY_CONTEXT_SDK_SOURCE_COMMIT,
  sourceTree = process.env.INFINITY_CONTEXT_SDK_SOURCE_TREE,
} = {}) {
  const actualRoot = await realpath(root);
  const identityPath = resolve(actualRoot, identityRelativePath);
  const packageJson = JSON.parse(await readFile(resolve(actualRoot, "package.json"), "utf8"));
  const commit = sourceCommit ?? await git(actualRoot, "rev-parse", "HEAD^{commit}");
  const tree = sourceTree ?? await git(actualRoot, "rev-parse", "HEAD^{tree}");
  const oidPattern = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/u;
  if (!oidPattern.test(commit) || !oidPattern.test(tree) || commit.length !== tree.length) {
    throw new Error("SDK source commit/tree identity is malformed");
  }
  if (typeof packageJson.name !== "string" || typeof packageJson.version !== "string") {
    throw new Error("SDK package identity is malformed");
  }
  if (!Array.isArray(packageJson.files) || packageJson.files.length === 0) {
    throw new Error("SDK package file inventory is missing");
  }

  const paths = new Set(["package.json"]);
  for (const item of packageJson.files) {
    if (typeof item !== "string" || item.length === 0 || item.startsWith("/") || item.includes("..")) {
      throw new Error("SDK package file declaration is unsafe");
    }
    await collect(resolve(actualRoot, item), actualRoot, paths);
  }
  paths.delete(identityRelativePath);
  const files = [];
  for (const path of [...paths].sort()) {
    const bytes = await safeRead(resolve(actualRoot, path), actualRoot, path);
    files.push({ path, sha256_hex: sha256(bytes) });
  }
  const identity = {
    files,
    package_name: packageJson.name,
    package_version: packageJson.version,
    schema_version: "infinity-context-typescript-sdk-artifact-identity.v1",
    source_commit: commit,
    source_git_tree_oid: tree,
  };
  await mkdir(dirname(identityPath), { recursive: true });
  await chmod(identityPath, 0o644).catch((error) => {
    if (error?.code !== "ENOENT") throw error;
  });
  await writeFile(identityPath, `${canonicalJson(identity)}\n`, { encoding: "utf8", mode: 0o444 });
  await chmod(identityPath, 0o444);
  return identity;
}

async function collect(path, root, paths) {
  let status;
  try { status = await lstat(path); }
  catch (error) {
    if (error?.code === "ENOENT") throw new Error(`SDK package file is missing: ${relative(root, path)}`);
    throw error;
  }
  if (status.isSymbolicLink()) throw new Error("SDK package inventory contains a symlink");
  if (status.isFile()) {
    paths.add(relative(root, path).split(sep).join("/"));
    return;
  }
  if (!status.isDirectory()) throw new Error("SDK package inventory contains a non-regular entry");
  for (const entry of await readdir(path)) await collect(resolve(path, entry), root, paths);
}

async function safeRead(path, root, label) {
  const actual = await realpath(path);
  if (actual !== root && !actual.startsWith(`${root}${sep}`)) throw new Error(`SDK package file escapes root: ${label}`);
  const status = await lstat(path);
  if (status.isSymbolicLink() || !status.isFile()) throw new Error(`SDK package file is not regular: ${label}`);
  return readFile(path);
}

async function git(root, ...args) {
  const result = await execFileAsync("git", ["-C", root, ...args], { encoding: "utf8" });
  return result.stdout.trim();
}

function sha256(bytes) { return createHash("sha256").update(bytes).digest("hex"); }

function canonicalJson(value) {
  if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number") {
    if (!Number.isSafeInteger(value)) throw new Error("identity contains an unsafe number");
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (typeof value === "object") {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
  }
  throw new Error("identity contains an unsupported value");
}

if (process.argv[1] !== undefined && await realpath(process.argv[1]).catch(() => "") === await realpath(fileURLToPath(import.meta.url))) {
  await createSdkArtifactIdentity();
}
