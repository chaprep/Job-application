import { build } from "esbuild";
import { spawnSync } from "node:child_process";
import { mkdir, rm } from "node:fs/promises";

const directory = ".test";
const outfile = `${directory}/frontend.test.mjs`;
await mkdir(directory, { recursive: true });
await build({
  entryPoints: ["tests/frontend.test.tsx"],
  outfile,
  bundle: true,
  platform: "node",
  format: "esm",
  packages: "external",
  jsx: "automatic",
});
try {
  const result = spawnSync(process.execPath, ["--test", outfile], {
    stdio: "inherit",
  });
  process.exitCode = result.status ?? 1;
} finally {
  await rm(outfile, { force: true });
}
