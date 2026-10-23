import fs from "node:fs";
import path from "node:path";

export function readVaultFile(vaultPath: string, relativePath: string): string {
  return fs.readFileSync(path.join(vaultPath, relativePath), "utf8");
}

export function writeVaultFile(
  vaultPath: string,
  relativePath: string,
  content: string,
): void {
  const target = path.join(vaultPath, relativePath);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, content, "utf8");
}

export function readCliCalls(
  vaultPath: string,
): Array<{ command: string; args: string[]; status: number }> {
  const logPath = path.join(vaultPath, ".infinity-context/real-plugin-cli-calls.jsonl");
  if (!fs.existsSync(logPath)) {
    return [];
  }
  return fs
    .readFileSync(logPath, "utf8")
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

export function pythonpath(repoRoot: string): string {
  return [
    "packages/infinity_context_core",
    "packages/infinity_context_adapters",
    "packages/infinity_context_server",
    "packages/infinity_context_benchmarks",
    "packages/infinity_context_sdk",
    "packages/infinity_context_obsidian",
  ]
    .map((relativePath) => path.join(repoRoot, relativePath))
    .join(path.delimiter);
}
