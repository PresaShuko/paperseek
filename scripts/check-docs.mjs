#!/usr/bin/env node
// Docs consistency checks (zero-dependency, run from repo root):
//   1. ZH/EN parity        — every docs/**/*.md mirrors docs/zh/**/*.md
//   2. Redirect stubs      — absolute site links in `noindex` stub pages resolve to real pages
//   3. Version consistency — pinned versions in docs match backend/pyproject.toml
// Exits non-zero and prints a report when any check fails.

import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const DOCS_DIR = join(REPO_ROOT, "docs");
const PYPROJECT = join(REPO_ROOT, "backend", "pyproject.toml");

// Excluded from the zh/en parity comparison (site assets and repo-local readmes).
const PARITY_EXCLUDES = new Set(["README.md", "zh/README.md"]);

// Version pin patterns. Each entry maps a match group to the expected form of the
// current release: "pip" (PEP 440, e.g. 1.0.0b1) or "display" (e.g. 1.0.0-beta1).
// Extend this array when new pin styles appear in the docs.
const VERSION_PATTERNS = [
  // python -m pip install "paperseek==1.0.0b1" / "paperseek-mcp==1.0.0b1"
  { name: "pip pin", re: /\bpaperseek(?:-[\w-]+)?==([^\s"')]+)/g, expect: "pip" },
  // PAPERSEEK_VERSION=1.0.0-beta1 docker compose up -d
  { name: "compose env pin", re: /\bPAPERSEEK_VERSION=["']?([^\s"';]+)/g, expect: "display" },
  // prose references: "Upgrade to 1.0.0-beta1", "new 1.0.0-beta1 docs"
  { name: "display prerelease literal", re: /\b\d+\.\d+\.\d+-(?:alpha|beta|rc)\d+\b/g, expect: "display" },
  // prose references in PEP 440 form: "install it from pip as 1.0.0b1"
  { name: "pep440 prerelease literal", re: /\b\d+\.\d+\.\d+(?:a|b|rc)\d+\b/g, expect: "pip" },
];

const rel = (abs) => relative(REPO_ROOT, abs).split("\\").join("/");

function listMarkdown(dir) {
  const out = [];
  const skip = new Set([".vitepress", "public", "dist", "node_modules"]);
  (function walk(current) {
    for (const entry of readdirSync(current, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        if (!skip.has(entry.name)) walk(join(current, entry.name));
      } else if (entry.isFile() && entry.name.endsWith(".md")) {
        out.push(join(current, entry.name));
      }
    }
  })(dir);
  return out.sort();
}

// A stub is a page whose YAML frontmatter mentions `noindex` (redirect pages
// kept for old URLs; their only job is to link to the replacement page).
function isStub(text) {
  if (!text.startsWith("---")) return false;
  const end = text.indexOf("\n---", 3);
  if (end === -1) return false;
  return /noindex/.test(text.slice(3, end));
}

// PEP 440 prerelease -> display form: 1.0.0b1 -> 1.0.0-beta1, 2.1.0rc3 -> 2.1.0-rc3.
function toDisplayVersion(version) {
  return version.replace(/(a|b|rc)(\d+)$/, (_, tag, num) => {
    const name = { a: "alpha", b: "beta", rc: "rc" }[tag];
    return `-${name}${num}`;
  });
}

function checkParity(files) {
  const en = new Set();
  const zh = new Set();
  for (const file of files) {
    const relToDocs = relative(DOCS_DIR, file).split("\\").join("/");
    if (PARITY_EXCLUDES.has(relToDocs)) continue;
    if (relToDocs.startsWith("zh/")) zh.add(relToDocs.slice(3));
    else en.add(relToDocs);
  }
  const missingZh = [...en].filter((p) => !zh.has(p)).sort();
  const missingEn = [...zh].filter((p) => !en.has(p)).sort();
  return { missingZh, missingEn, ok: missingZh.length === 0 && missingEn.length === 0 };
}

function checkStubTargets(files) {
  const broken = [];
  let stubCount = 0;
  let linkCount = 0;
  for (const file of files) {
    const text = readFileSync(file, "utf8");
    if (!isStub(text)) continue;
    stubCount += 1;
    for (const match of text.matchAll(/\]\((\/[^)\s]+)\)/g)) {
      linkCount += 1;
      const target = match[1].slice(1); // strip leading "/"
      const candidates = target.endsWith("/")
        ? [`${target}index.md`]
        : [`${target}.md`, `${target}/index.md`];
      if (!candidates.some((c) => existsSync(join(DOCS_DIR, c)))) {
        const line = text.slice(0, match.index).split("\n").length;
        broken.push({ file: rel(file), line, target: match[1] });
      }
    }
  }
  return { broken, stubCount, linkCount, ok: broken.length === 0 };
}

function readCurrentVersion() {
  const text = readFileSync(PYPROJECT, "utf8");
  const match = text.match(/^version\s*=\s*"([^"]+)"/m);
  if (!match) throw new Error(`could not find version in ${rel(PYPROJECT)}`);
  return match[1];
}

function checkVersions(files) {
  const pipVersion = readCurrentVersion();
  const displayVersion = toDisplayVersion(pipVersion);
  const expected = { pip: pipVersion, display: displayVersion };
  const mismatches = [];
  let scanned = 0;
  for (const file of files) {
    const text = readFileSync(file, "utf8");
    if (isStub(text)) continue; // stubs only hold redirect links; skip them
    if (rel(file).endsWith("changelog.md")) continue; // the changelog names every past release
    scanned += 1;
    const lineStarts = [0];
    for (let i = 0; i < text.length; i += 1) {
      if (text[i] === "\n") lineStarts.push(i + 1);
    }
    const lineOf = (offset) => {
      let lo = 0;
      let hi = lineStarts.length - 1;
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (lineStarts[mid] <= offset) lo = mid;
        else hi = mid - 1;
      }
      return lo + 1;
    };
    const seen = new Set();
    for (const { name, re, expect } of VERSION_PATTERNS) {
      for (const match of text.matchAll(re)) {
        const found = match[1] ?? match[0];
        if (found === expected[expect]) continue;
        const line = lineOf(match.index);
        const key = `${line}|${found}`;
        if (seen.has(key)) continue; // same literal caught by two patterns
        seen.add(key);
        mismatches.push({ file: rel(file), line, found, expected: expected[expect], pattern: name });
      }
    }
  }
  return { mismatches, pipVersion, displayVersion, scanned, ok: mismatches.length === 0 };
}

function main() {
  const files = listMarkdown(DOCS_DIR);
  const failures = [];

  console.log(`Scanning ${files.length} markdown files under ${rel(DOCS_DIR)}/\n`);

  const parity = checkParity(files);
  console.log(`[1/3] zh/en parity`);
  if (parity.ok) {
    console.log("  OK — every English page has a Chinese mirror and vice versa.\n");
  } else {
    failures.push("zh/en parity");
    for (const p of parity.missingZh) console.log(`  MISSING zh mirror: docs/${p}  (expected docs/zh/${p})`);
    for (const p of parity.missingEn) console.log(`  MISSING en source: docs/zh/${p}  (expected docs/${p})`);
    console.log("");
  }

  const stubs = checkStubTargets(files);
  console.log(`[2/3] redirect-stub targets (${stubs.stubCount} stubs, ${stubs.linkCount} absolute links)`);
  if (stubs.ok) {
    console.log("  OK — every stub link resolves to an existing page.\n");
  } else {
    failures.push("redirect-stub targets");
    for (const b of stubs.broken) console.log(`  BROKEN ${b.file}:${b.line}  ->  ${b.target}`);
    console.log("");
  }

  const versions = checkVersions(files);
  console.log(`[3/3] version pins (current release: ${versions.pipVersion} / display ${versions.displayVersion}; ${versions.scanned} non-stub pages scanned)`);
  if (versions.ok) {
    console.log("  OK — every pinned version matches the current release.\n");
  } else {
    failures.push("version pins");
    for (const m of versions.mismatches) {
      console.log(`  MISMATCH ${m.file}:${m.line}  found "${m.found}", expected "${m.expected}" (${m.pattern})`);
    }
    console.log("");
  }

  if (failures.length > 0) {
    console.error(`docs check FAILED: ${failures.join(", ")}`);
    process.exit(1);
  }
  console.log("docs check passed.");
}

main();
