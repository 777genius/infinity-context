import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../../..");
const serverApiDir = path.join(
  repoRoot,
  "packages/infinity_context_server/infinity_context_server/api/v1",
);
const sdkSrcDir = path.join(repoRoot, "packages/infinity_context_ts_sdk/src");

const allowedMissing = new Map([
  [
    "GET /v1/healthz",
    "healthz is an include_in_schema=false liveness alias; SDK exposes system.health() for /v1/health.",
  ],
]);

const serverEndpoints = readServerEndpoints(serverApiDir);
const sdkEndpoints = readSdkEndpoints(sdkSrcDir);
const allowedExceptions = [...serverEndpoints].filter(
  (endpoint) => allowedMissing.has(endpoint) && !sdkEndpoints.has(endpoint),
);
const requiredServerEndpoints = [...serverEndpoints].filter((endpoint) => !allowedMissing.has(endpoint));
const missing = requiredServerEndpoints
  .filter((endpoint) => !sdkEndpoints.has(endpoint))
  .sort();
const unknownSdkEndpoints = [...sdkEndpoints]
  .filter((endpoint) => !serverEndpoints.has(endpoint))
  .sort();

if (missing.length > 0 || unknownSdkEndpoints.length > 0) {
  console.error("TypeScript SDK API parity check failed.");
  if (missing.length > 0) {
    console.error("Missing SDK endpoints:");
    for (const endpoint of missing) {
      console.error(`  - ${endpoint}`);
    }
  }
  if (unknownSdkEndpoints.length > 0) {
    console.error("SDK endpoints missing from the server API:");
    for (const endpoint of unknownSdkEndpoints) {
      console.error(`  - ${endpoint}`);
    }
  }
  process.exitCode = 1;
} else {
  console.log(
    `Bidirectional API parity ok: ${sdkEndpoints.size} SDK endpoints match ${requiredServerEndpoints.length} required server endpoints ` +
      `(${allowedExceptions.length} active documented exception).`,
  );
}

function readServerEndpoints(directory) {
  const endpoints = new Set();
  for (const file of readdirSync(directory).sort()) {
    if (!file.endsWith(".py") || file === "__init__.py") {
      continue;
    }
    const filename = path.join(directory, file);
    const source = readFileSync(filename, "utf8");
    if (!source.includes("@router.")) {
      continue;
    }
    const routerPrefix = routerPrefixFrom(source);
    const routePattern = /@router\.(get|post|patch|delete|put)\(\s*(["'])(.*?)\2([\s\S]*?)\)\s*\n/g;
    for (const match of source.matchAll(routePattern)) {
      const [, method, , routePath, options] = match;
      if (options.includes("include_in_schema=False")) {
        endpoints.add(normalizeEndpoint(method, `/v1${routerPrefix}${routePath}`));
        continue;
      }
      endpoints.add(normalizeEndpoint(method, `/v1${routerPrefix}${routePath}`));
    }
  }
  return endpoints;
}

function readSdkEndpoints(directory) {
  const endpoints = new Set();
  for (const filename of walk(directory)) {
    if (!filename.endsWith(".ts")) {
      continue;
    }
    const source = readFileSync(filename, "utf8");
    const requestPattern =
      /method:\s*(["'])(GET|POST|PATCH|DELETE|PUT)\1[\s\S]{0,900}?path:\s*([`'"])([\s\S]*?)\3/g;
    for (const match of source.matchAll(requestPattern)) {
      const [, , method, , rawPath] = match;
      endpoints.add(normalizeEndpoint(method, templatePathToRoute(rawPath)));
    }
  }
  return endpoints;
}

function routerPrefixFrom(source) {
  const routerMatch = source.match(/router\s*=\s*APIRouter\(([\s\S]*?)\n\)/m);
  if (!routerMatch) {
    return "";
  }
  const prefixMatch = routerMatch[1].match(/prefix\s*=\s*(["'])(.*?)\1/);
  return prefixMatch?.[2] ?? "";
}

function templatePathToRoute(rawPath) {
  return rawPath.replace(/\$\{[\s\S]*?\}/g, "{param}").replace(/\s+/g, "");
}

function normalizeEndpoint(method, rawPath) {
  return `${method.toUpperCase()} ${normalizeRoutePath(rawPath)}`;
}

function normalizeRoutePath(rawPath) {
  const normalized = rawPath
    .replace(/\/+/g, "/")
    .replace(/\/$/, "")
    .replace(/\{[^/{}]+}/g, "{param}");
  return normalized === "" ? "/" : normalized;
}

function* walk(directory) {
  for (const entry of readdirSync(directory).sort()) {
    const filename = path.join(directory, entry);
    if (filename.includes(`${path.sep}dist${path.sep}`) || filename.includes(`${path.sep}node_modules${path.sep}`)) {
      continue;
    }
    if (statSync(filename).isDirectory()) {
      yield* walk(filename);
    } else {
      yield filename;
    }
  }
}
