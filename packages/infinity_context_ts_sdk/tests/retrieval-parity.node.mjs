import { test } from "node:test";
import assert from "node:assert/strict";
import { cp, mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

const sdkRoot = new URL("../", import.meta.url);
// Resolve relative to the SDK package, alongside its sibling Python package.
const pythonSource = await readFile(new URL("../infinity_context_sdk/infinity_context_sdk/retrieval.py", sdkRoot), "utf8");
const tsSource = await readFile(new URL("src/resources/context.ts", sdkRoot), "utf8");

const mutations = [
  ["TS V2 wrong endpoint", "ts", 'path: "/v1/context/retrieve" }, false', 'path: "/v1/context/retrieve-v3" }, false'],
  ["TS V3 falls back to V2", "ts", 'path: "/v1/context/retrieve-v3" }, true', 'path: "/v1/context/retrieve" }, true'],
  ["TS V3 method removed", "ts", "async retrieveV3(", "async removedV3("],
  ["TS version flag lost", "ts", 'path: "/v1/context/retrieve-v3" }, true', 'path: "/v1/context/retrieve-v3" }, false'],
  ["TS transport ignores route", "ts", "...route,", 'method: "POST", path: "/v1/context/retrieve",'],
  ["Python V2 method removed", "py", "def retrieve_context(", "def removed_v2("],
  ["Python V3 method removed", "py", "def retrieve_context_v3(", "def removed_v3("],
  ["Python V3 flag lost", "py", "v3=True,", "v3=False,"],
  ["Python V3 endpoint selection lost", "py", 'V3_ENDPOINT if v3 else "/v1/context/retrieve"', '"/v1/context/retrieve"'],
  ["Python V2 endpoint wrong", "py", 'V3_ENDPOINT if v3 else "/v1/context/retrieve"', "V3_ENDPOINT"],
  ["Python stream verb changed", "py", 'client.stream("POST", endpoint, content=payload)', 'client.stream("GET", endpoint, content=payload)'],
  ["Python stream endpoint ignored", "py", 'client.stream("POST", endpoint, content=payload)', 'client.stream("POST", "/v1/context/retrieve", content=payload)'],
  ["Python forwarding lost", "py", "else _read_response(client, payload, maximum_bytes, endpoint)", "else _read_response(client, payload, maximum_bytes)"],
  ["Python cancellation invariant lost", "py", "await asyncio.gather(request_task, cancellation_task", "await asyncio.gather(request_task"],
];

for (const mutation of [null, ...mutations]) {
  test(mutation?.[0] ?? "current V2/V3 routing passes", async () => {
    const root = await mkdtemp(join(tmpdir(), "retrieval-parity-"));
    try {
      const sdk = join(root, "infinity_context_ts_sdk");
      const py = join(root, "infinity_context_sdk/infinity_context_sdk");
      await mkdir(join(sdk, "scripts"), { recursive: true });
      await mkdir(join(sdk, "src/resources"), { recursive: true });
      await mkdir(py, { recursive: true });
      await cp(new URL("fixtures", sdkRoot), join(sdk, "fixtures"), { recursive: true });
      await cp(new URL("package.json", sdkRoot), join(sdk, "package.json"));
      await cp(new URL("scripts/check-retrieval-parity.mjs", sdkRoot), join(sdk, "scripts/check-retrieval-parity.mjs"));
      let ts = tsSource;
      let python = pythonSource;
      if (mutation) {
        const [, language, before, after] = mutation;
        assert.ok((language === "ts" ? ts : python).includes(before), "mutation must apply");
        if (language === "ts") ts = ts.replace(before, after);
        else python = python.replace(before, after);
      }
      await writeFile(join(sdk, "src/resources/context.ts"), ts);
      await writeFile(join(py, "retrieval.py"), python);
      const result = spawnSync(process.execPath, [join(sdk, "scripts/check-retrieval-parity.mjs")], { encoding: "utf8" });
      if (mutation) {
        assert.notEqual(result.status, 0);
        assert.match(result.stderr, /SDK (endpoint|route transport) parity failed/);
      } else {
        assert.equal(result.status, 0, result.stderr);
      }
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
}
