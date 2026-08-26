import { readdir, readFile } from "node:fs/promises";
import { extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = new URL("..", import.meta.url);
const packageRootPath = fileURLToPath(packageRoot);
const sourceRoots = ["src", "scripts"];
const sourceExtensions = new Set([".ts", ".mjs"]);
const targetLines = parsePositiveInteger(process.env.INFINITY_CONTEXT_SDK_TARGET_LINES) ?? 900;
const hardCapLines = parsePositiveInteger(process.env.INFINITY_CONTEXT_SDK_HARD_CAP_LINES) ?? 1000;

const files = [];
for (const root of sourceRoots) {
  files.push(...await listSourceFiles(join(packageRootPath, root)));
}

const oversized = [];
const warnings = [];
for (const file of files) {
  const text = await readFile(file, "utf8");
  const lines = countLines(text);
  const displayPath = relative(packageRootPath, file);
  if (lines > hardCapLines) {
    oversized.push({ path: displayPath, lines });
    continue;
  }
  if (lines > targetLines) {
    warnings.push({ path: displayPath, lines });
  }
}

if (warnings.length > 0) {
  process.stderr.write(
    `Architecture size target warnings (${targetLines} lines): ${formatEntries(warnings)}\n`,
  );
}

if (oversized.length > 0) {
  throw new Error(`Architecture hard cap exceeded (${hardCapLines} lines): ${formatEntries(oversized)}`);
}

process.stdout.write(
  `Architecture gate ok: ${files.length} source files, hard cap ${hardCapLines} lines, target ${targetLines} lines\n`,
);

async function listSourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const found = [];
  for (const entry of entries) {
    const absolutePath = join(directory, entry.name);
    if (entry.isDirectory()) {
      found.push(...await listSourceFiles(absolutePath));
      continue;
    }
    if (entry.isFile() && sourceExtensions.has(extname(entry.name))) {
      found.push(absolutePath);
    }
  }
  return found.sort();
}

function countLines(text) {
  if (text.length === 0) {
    return 0;
  }
  return text.endsWith("\n") ? text.split("\n").length - 1 : text.split("\n").length;
}

function parsePositiveInteger(value) {
  if (value === undefined) {
    return undefined;
  }
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined;
}

function formatEntries(entries) {
  return entries.map((entry) => `${entry.path}=${entry.lines}`).join(", ");
}
