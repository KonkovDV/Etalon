// Проверка сайта в браузере перед публикацией в Pages.
//
//   python3 scripts/build_site.py --out public
//   (cd scripts && npm ci)            # playwright и axe-core из package-lock.json
//   node scripts/check_site.js public [каталог-для-снимков]
//
// Сайт отдаётся по HTTP из подкаталога /Etalon/, как его отдают GitLab Pages и GitHub Pages
// для проекта. Код выхода 1 — есть замечания. Проверяется:
//   1. каждая страница на 8 устройствах в светлой и тёмной теме: ответ 200, нет ошибок в консоли
//      и неудачных запросов, нет горизонтальной прокрутки страницы, картинки загрузились и у всех
//      есть alt, в тексте нет NaN / undefined / Infinity / None, пункты меню и карточки не меньше
//      24 × 24 px (WCAG 2.2, 2.5.8);
//   2. все внутренние ссылки ведут на существующие страницы, а якоря — на существующие id;
//   3. axe-core: WCAG 2.0/2.1/2.2 A и AA на каждой странице в обеих темах (на компьютере).
// Движок — Chromium.
"use strict";

const fs = require("fs");
const http = require("http");
const path = require("path");
const { chromium, devices } = require("playwright");

const BASE = "/Etalon/";
const TYPES = { ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
  ".json": "application/json", ".js": "text/javascript", ".webp": "image/webp" };
const DEVICES = [
  ["iPhone SE", devices["iPhone SE"]],
  ["iPhone 14", devices["iPhone 14"]],
  ["Pixel 7", devices["Pixel 7"]],
  ["Galaxy S9+", devices["Galaxy S9+"]],
  ["iPad Mini", devices["iPad Mini"]],
  ["iPad Pro 11 landscape", devices["iPad Pro 11 landscape"]],
  ["Laptop 1366", { viewport: { width: 1366, height: 768 } }],
  ["Desktop 1920", { viewport: { width: 1920, height: 1080 } }],
];
const BAD_TEXT = /\b(NaN|undefined|Infinity|None)\b/;

function serve(root) {
  const base = path.resolve(root);
  const server = http.createServer((req, res) => {
    let rel = decodeURIComponent(new URL(req.url, "http://localhost").pathname);
    if (!rel.startsWith(BASE)) { res.writeHead(404).end(); return; }
    rel = rel.slice(BASE.length - 1).replace(/\/$/, "/index.html");
    const file = path.resolve(base, "." + rel);
    if (!file.startsWith(base + path.sep) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      res.writeHead(404, { "Content-Type": TYPES[".html"] });
      fs.createReadStream(path.join(base, "404.html")).pipe(res);
      return;
    }
    res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve(server)));
}

function listPages(root) {
  const out = [];
  const walk = (dir) => {
    for (const name of fs.readdirSync(dir).sort()) {
      const full = path.join(dir, name);
      if (fs.statSync(full).isDirectory()) walk(full);
      else if (name.endsWith(".html") && name !== "404.html") out.push(path.relative(root, full).split(path.sep).join("/"));
    }
  };
  walk(root);
  return out;
}

async function checkPage(page, url, problems, label) {
  const consoleErrors = [];
  const failed = [];
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
  page.on("requestfailed", (r) => failed.push(r.url()));
  page.on("response", (r) => { if (r.status() >= 400) failed.push(r.status() + " " + r.url()); });
  const resp = await page.goto(url, { waitUntil: "load" });
  if (!resp || resp.status() !== 200) problems.push(`${label}: HTTP ${resp && resp.status()}`);
  const facts = await page.evaluate(() => {
    const doc = document.documentElement;
    const imgs = [...document.images];
    const targets = [...document.querySelectorAll("nav a, footer a, a.card, a.brand, summary")]
      .map((el) => { const r = el.getBoundingClientRect(); return { t: el.textContent.trim().slice(0, 30), w: r.width, h: r.height }; })
      .filter((r) => r.w > 0 && (r.w < 24 || r.h < 24));
    return {
      overflow: doc.scrollWidth - window.innerWidth,
      noAlt: imgs.filter((i) => !i.hasAttribute("alt")).map((i) => i.src),
      broken: imgs.filter((i) => i.complete && i.naturalWidth === 0).map((i) => i.currentSrc || i.src),
      text: document.body.innerText,
      small: targets,
    };
  });
  if (facts.overflow > 1) problems.push(`${label}: горизонтальная прокрутка ${facts.overflow}px`);
  if (facts.noAlt.length) problems.push(`${label}: картинки без alt: ${facts.noAlt.join(", ")}`);
  if (facts.broken.length) problems.push(`${label}: картинки не загрузились: ${facts.broken.join(", ")}`);
  const bad = facts.text.match(BAD_TEXT);
  if (bad) problems.push(`${label}: в тексте «${bad[0]}»`);
  if (facts.small.length) problems.push(`${label}: цели касания меньше 24px: ${JSON.stringify(facts.small)}`);
  if (consoleErrors.length) problems.push(`${label}: ошибки консоли: ${consoleErrors.join(" | ")}`);
  if (failed.length) problems.push(`${label}: неудачные запросы: ${failed.join(", ")}`);
}

async function checkLinks(browser, origin, pages, problems) {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const idsByPage = new Map();
  const links = [];
  for (const p of pages) {
    const url = origin + BASE + p;
    await page.goto(url);
    const found = await page.evaluate(() => ({
      ids: [...document.querySelectorAll("[id]")].map((e) => e.id),
      hrefs: [...document.querySelectorAll("a[href]")].map((a) => a.href),
    }));
    idsByPage.set(url.split("#")[0], new Set(found.ids));
    for (const h of found.hrefs) links.push([p, h]);
  }
  const checked = new Map();
  for (const [from, href] of links) {
    if (!href.startsWith(origin)) continue;  // внешние ссылки не проверяются
    const [target, anchor] = href.split("#");
    if (!checked.has(target)) {
      const r = await page.request.get(target);
      checked.set(target, r.status());
    }
    if (checked.get(target) !== 200) { problems.push(`${from}: ссылка ${href} -> ${checked.get(target)}`); continue; }
    if (anchor) {
      let ids = idsByPage.get(target);
      if (!ids) {
        await page.goto(target);
        ids = new Set(await page.evaluate(() => [...document.querySelectorAll("[id]")].map((e) => e.id)));
        idsByPage.set(target, ids);
      }
      if (!ids.has(decodeURIComponent(anchor))) problems.push(`${from}: нет якоря #${decodeURIComponent(anchor)} на ${target}`);
    }
  }
  await ctx.close();
  return links.length;
}

async function checkAxe(browser, origin, pages, problems) {
  const axePath = require.resolve("axe-core/axe.min.js");
  for (const scheme of ["light", "dark"]) {
    // bypassCSP: только чтобы подложить axe; страницы сайта сами скриптов не грузят
    const ctx = await browser.newContext({ viewport: { width: 1366, height: 900 }, colorScheme: scheme, bypassCSP: true });
    const page = await ctx.newPage();
    for (const p of pages) {
      await page.goto(origin + BASE + p);
      await page.addScriptTag({ path: axePath });
      const res = await page.evaluate(async () => {
        const r = await window.axe.run(document, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] } });
        return r.violations.map((v) => `${v.id} (${v.impact}): ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join("; ")}`);
      });
      for (const v of res) problems.push(`axe ${scheme} ${p}: ${v}`);
    }
    await ctx.close();
  }
}

(async () => {
  const root = process.argv[2] || "public";
  const shots = process.argv[3];
  if (shots) fs.mkdirSync(shots, { recursive: true });
  const server = await serve(root);
  const origin = `http://127.0.0.1:${server.address().port}`;
  const pages = listPages(root);
  const problems = [];
  const browser = await chromium.launch();
  try {
    for (const [name, dev] of DEVICES) {
      for (const scheme of ["light", "dark"]) {
        const ctx = await browser.newContext({ ...dev, colorScheme: scheme });
        for (const p of pages) {
          const page = await ctx.newPage();
          await checkPage(page, origin + BASE + p, problems, `${name} ${scheme} ${p}`);
          if (shots && (p === "index.html" || p === "report/index.html")) {
            const file = `${name}-${scheme}-${p.replace(/\//g, "_")}`.replace(/[^\w.-]+/g, "_") + ".png";
            await page.screenshot({ path: path.join(shots, file), fullPage: true });
          }
          await page.close();
        }
        await ctx.close();
      }
    }
    const nLinks = await checkLinks(browser, origin, pages, problems);
    await checkAxe(browser, origin, pages, problems);
    console.log(`check_site: ${pages.length} страниц × ${DEVICES.length} устройств × 2 темы, ${nLinks} ссылок, axe WCAG 2.2 AA`);
  } finally {
    await browser.close();
    server.close();
  }
  for (const p of problems) console.log("  " + p);
  console.log(`check_site: замечаний ${problems.length}`);
  process.exit(problems.length ? 1 : 0);
})();
