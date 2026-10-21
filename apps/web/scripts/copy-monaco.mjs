// Copies Monaco's AMD build into public/ so the editor loads from our own origin (strict CSP, no CDN).
import { cpSync, existsSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
let pkgDir = join(here, "..", "node_modules", "monaco-editor");
if (!existsSync(pkgDir)) {
  try {
    pkgDir = dirname(require.resolve("monaco-editor/package.json"));
  } catch {
    console.warn("monaco-editor not installed yet; skipping copy");
    process.exit(0);
  }
}
const source = join(pkgDir, "min", "vs");
const target = join(here, "..", "public", "monaco", "vs");
if (!existsSync(source)) {
  console.warn(`monaco build not found at ${source}`);
  process.exit(0);
}
mkdirSync(target, { recursive: true });
cpSync(source, target, { recursive: true });
console.log(`monaco copied to ${target}`);
