import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

const expectedExports = [
  ["@infinity-context/sdk", "InfinityContextClient"],
  ["@infinity-context/sdk/instrumentation", "noopInstrumentation"],
  ["@infinity-context/sdk/pagination", "iterateCursorItems"],
  ["@infinity-context/sdk/runtime", "assertFullMemoryReady"],
  ["@infinity-context/sdk/canary", "runRuntimeCanary"],
  ["@infinity-context/sdk/workflows", "MemoryWorkflows"],
];

for (const [specifier, exportName] of expectedExports) {
  const esm = await import(specifier);
  if (typeof esm[exportName] === "undefined") {
    throw new Error(`Missing ESM export ${exportName} from ${specifier}`);
  }

  const cjs = require(specifier);
  if (typeof cjs[exportName] === "undefined") {
    throw new Error(`Missing CJS export ${exportName} from ${specifier}`);
  }
}

console.log(`Package exports ok: ${expectedExports.length} entry points`);
