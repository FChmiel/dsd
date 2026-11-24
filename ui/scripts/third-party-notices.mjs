import { execFileSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

const UI = resolve(import.meta.dirname, "..");
const OUT = resolve(UI, "../THIRD_PARTY_NOTICES.md");

const FONTS = [
  ["Excalifont", "SIL Open Font License 1.1"],
  ["Virgil", "SIL Open Font License 1.1"],
  ["Nunito", "SIL Open Font License 1.1"],
  ["Lilita One", "SIL Open Font License 1.1"],
  ["Cascadia Code", "SIL Open Font License 1.1"],
  ["Liberation Sans", "SIL Open Font License 1.1"],
  ["Assistant", "SIL Open Font License 1.1"],
  ["Comic Shanns", "MIT"],
];

const OVERRIDES = {
  khroma: { license: "MIT", author: "Fabio Spampinato" },
  "@excalidraw/excalidraw": { author: "2020 Excalidraw" },
};

const dirs = execFileSync("npm", ["ls", "--omit=dev", "--all", "--parseable"], { cwd: UI, encoding: "utf8" })
  .trim().split("\n").slice(1);

const pkgs = new Map();
for (const dir of dirs) {
  const meta = JSON.parse(readFileSync(join(dir, "package.json"), "utf8"));
  const key = `${meta.name}@${meta.version}`;
  if (pkgs.has(key)) continue;
  const file = existsSync(dir) && readdirSync(dir).find((f) => /^(licen[cs]e|copying)(\.|$)/i.test(f));
  const license = typeof meta.license === "string" ? meta.license
    : meta.license?.type ?? meta.licenses?.map((l) => l.type ?? l).join(" OR ") ?? "unknown";
  const author = typeof meta.author === "string" ? meta.author : meta.author?.name;
  pkgs.set(key, { name: meta.name, version: meta.version, license, author, text: file ? readFileSync(join(dir, file), "utf8").trim() : null, ...OVERRIDES[meta.name] });
}

const list = [...pkgs.values()].sort((a, b) => a.name.localeCompare(b.name));
const out = [
  "# Third-party notices",
  "",
  "The dsd app's web UI (`src/dsd/web/dist`, built from `ui/`) bundles the open-source packages below.",
  "Their licences and notices follow. Regenerate this file with `npm run notices` in `ui/`.",
  "",
  "## Fonts",
  "",
  "The whiteboard editor ships these fonts from `@excalidraw/excalidraw`:",
  "",
  ...FONTS.map(([name, lic]) => `- ${name}: ${lic}`),
  "",
  "## Packages",
  "",
  "| Package | Version | Licence |",
  "| --- | --- | --- |",
  ...list.map((p) => `| ${p.name} | ${p.version} | ${p.license} |`),
  "",
  "## Licence texts",
  "",
];
for (const p of list) {
  out.push(`### ${p.name}@${p.version}`, "");
  out.push(p.text ? ["```", p.text.replace(/```/g, "'''"), "```"].join("\n") : `Licensed under ${p.license}${p.author ? `, copyright ${p.author}` : ""}. The package ships no licence file; see its repository.`, "");
}
writeFileSync(OUT, out.join("\n"));
console.log(`wrote ${list.length} packages to ${OUT}`);
