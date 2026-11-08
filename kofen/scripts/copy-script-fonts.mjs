#!/usr/bin/env node
/**
 * Self-hosts the zh / ar script fonts as standalone stylesheets in public/fonts/.
 *
 * Why not next/font? The [locale] layout is shared by every locale, and next/font
 * emits its @font-face CSS for every page that imports it: Noto Sans SC alone is
 * ~186 KB of render-blocking CSS. These stylesheets are linked only on /zh and /ar,
 * and unicode-range means a browser only downloads the slices a page actually uses.
 *
 * Runs automatically before `dev` and `build` (see package.json). Output is gitignored.
 */
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const out = resolve(root, "public/fonts");

const FONTS = [
  // Every slice: the CJK set is split into ~100 unicode ranges.
  { pkg: "@fontsource-variable/noto-sans-sc", name: "noto-sans-sc", keep: () => true },
  // Arabic glyphs only; Latin text on /ar keeps Geist.
  { pkg: "@fontsource-variable/noto-sans-arabic", name: "noto-sans-arabic", keep: (block) => block.includes("-arabic-wght-") },
];

for (const { pkg, name, keep } of FONTS) {
  const pkgDir = resolve(root, "node_modules", pkg);
  const css = readFileSync(resolve(pkgDir, "index.css"), "utf8");
  const blocks = css.split(/(?=\/\* )/).filter((b) => b.includes("@font-face") && keep(b));
  mkdirSync(resolve(out, name), { recursive: true });
  const rewritten = blocks.map((block) =>
    block.replace(/url\(\.\/files\/([^)]+)\)/g, (_, file) => {
      copyFileSync(resolve(pkgDir, "files", file), resolve(out, name, file));
      return `url(/fonts/${name}/${file})`;
    }),
  );
  writeFileSync(resolve(out, `${name}.css`), rewritten.join("").trim() + "\n");
  console.log(`public/fonts/${name}.css: ${blocks.length} faces`);
}
