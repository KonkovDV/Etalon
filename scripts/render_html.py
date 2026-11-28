#!/usr/bin/env python3
"""Самодостаточный HTML-отчёт из report.json (inline SVG, без внешних ресурсов).

    python3 scripts/render_html.py HG002.report.json -o HG002.report.html

Вызывается из make_report.py; отдельно — чтобы перерисовать отчёт без пересчёта.
Палитра: слоты 1–3 эталонной категориальной палитры, проверены валидатором на
CVD-различимость во всех парах в светлой и тёмной теме. На светлом фоне слоты 2–3
ниже 3:1, поэтому у каждого графика есть подписи и таблица данных.
"""

import argparse
import base64
import hashlib
import html
import json
import math
import sys

CSS = """
:root{color-scheme:light;--bg:#f6f7f9;--surface:#ffffff;--ink:#191919;--ink-2:#5c5f66;--line:#e3e5e8;
--grid:#eceef1;--s1:#257de0;--s2:#f47230;--s3:#00b894;--good:#0aac23;--good-ink:#006c10;--bad:#dc3c3d;
--bad-ink:#b02a2b;--chip:#eef4fd}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])){color-scheme:dark;--bg:#111214;
--surface:#191919;--ink:#efefef;--ink-2:#9c9c9c;--line:#2c2e31;--grid:#26282b;--s1:#338ced;--s2:#e76624;
--s3:#00a888;--good:#0aac23;--good-ink:#3ccf55;--bad:#dc3c3d;--bad-ink:#f07a7b;--chip:#1d2a3a}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#111214;--surface:#191919;--ink:#efefef;--ink-2:#9c9c9c;
--line:#2c2e31;--grid:#26282b;--s1:#338ced;--s2:#e76624;--s3:#00a888;--good:#0aac23;--good-ink:#3ccf55;
--bad:#dc3c3d;--bad-ink:#f07a7b;--chip:#1d2a3a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,
"Helvetica Neue",Arial,sans-serif;-webkit-font-smoothing:antialiased}
main{max-width:1080px;margin:0 auto;padding:28px 16px 64px}
header h1{font-size:28px;line-height:1.2;margin:0 0 6px;letter-spacing:-.01em}
header p{margin:0;color:var(--ink-2)}
.badge{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;font-weight:600;
font-size:13px;border:1px solid currentColor;vertical-align:middle}
.badge.ok{color:var(--good-ink)}.badge.fail{color:var(--bad-ink)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:22px 0 8px}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.tile .k{font-size:12.5px;color:var(--ink-2)}
.tile .v{font-size:26px;font-weight:650;margin-top:2px;font-variant-numeric:tabular-nums}
.tile .s{font-size:12px;color:var(--ink-2);font-variant-numeric:tabular-nums}
section{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:20px 20px 14px;
margin-top:18px}
section h2{font-size:19px;margin:0 0 4px}
section .lead{color:var(--ink-2);margin:0 0 12px;max-width:820px}
h3{font-size:15px;margin:18px 0 6px}
.legend{display:flex;flex-wrap:wrap;gap:16px;font-size:13px;color:var(--ink);margin:4px 0 8px}
.legend span{display:inline-flex;align-items:center;gap:6px}
.sw{width:12px;height:12px;border-radius:3px;display:inline-block}
.sw.line{height:3px;border-radius:2px}
.sw.c1{background:var(--s1)}.sw.c2{background:var(--s2)}.sw.c3{background:var(--s3)}
svg{display:block;width:100%;height:auto;overflow:visible}
svg text{fill:var(--ink-2);font-size:12px;font-family:inherit}
svg .lbl{fill:var(--ink)}
.grid{stroke:var(--grid);stroke-width:1}
.axis{stroke:var(--line);stroke-width:1}
.mark{cursor:default}
.mark:hover{opacity:.82}
table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--ink-2);font-weight:600}
td.num,th.num{text-align:right}
details{margin-top:10px}
summary{cursor:pointer;color:var(--ink-2);font-size:13px;padding:5px 0;min-height:24px}
.ok-ink{color:var(--good-ink);font-weight:600}.bad-ink{color:var(--bad-ink);font-weight:600}
.note{font-size:13px;color:var(--ink-2)}
code{font:12.5px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;background:var(--chip);padding:1px 5px;
border-radius:5px}
.scroll{overflow-x:auto}
#tip{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--line);
border-radius:8px;padding:6px 9px;font-size:12px;line-height:1.4;box-shadow:0 4px 18px rgba(0,0,0,.12);
display:none;max-width:320px;z-index:10;white-space:pre-line}
footer{margin-top:24px;color:var(--ink-2);font-size:12px}
"""

JS = """
(function(){var tip=document.getElementById('tip');
document.addEventListener('mousemove',function(e){var t=e.target.closest?e.target.closest('[data-tip]'):null;
if(!t){tip.style.display='none';return;}tip.textContent=t.getAttribute('data-tip');tip.style.display='block';
var x=e.clientX+14,y=e.clientY+14,w=tip.offsetWidth,h=tip.offsetHeight;
if(x+w>window.innerWidth-8){x=e.clientX-w-14;}if(y+h>window.innerHeight-8){y=e.clientY-h-14;}
tip.style.left=x+'px';tip.style.top=y+'px';});})();
"""

SERIES = ["var(--s1)", "var(--s2)", "var(--s3)"]
SWATCH = {"var(--s1)": "c1", "var(--s2)": "c2", "var(--s3)": "c3"}


def csp_hash(text):
    """CSP source for one inline <style>/<script>: only this exact text may run."""
    return "'sha256-%s'" % base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")


CSP = "default-src 'none'; img-src data:; style-src %s; script-src %s; base-uri 'none'; form-action 'none'" % (
    csp_hash(CSS),
    csp_hash(JS),
)


def esc(s):
    return html.escape("" if s is None else str(s), quote=True)


def f(x, d=3):
    return "–" if x is None else ("%." + str(d) + "f") % x


def pct(x, d=1):
    return "–" if x is None else ("%." + str(d) + "f %%") % (100 * x)


def nice_ticks(lo, hi, n=5):
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=mag * 10)
    start = math.ceil(lo / step) * step
    ticks, v = [], start
    while v <= hi + 1e-12:
        ticks.append(round(v, 10))
        v += step
    return ticks


def bar_h(x0, y, w, h, r=4):
    """Горизонтальный столбец, скруглён только конец с данными."""
    r = max(0.0, min(r, w / 2.0, h / 2.0))
    return "M%.1f,%.1f H%.1f Q%.1f,%.1f %.1f,%.1f V%.1f Q%.1f,%.1f %.1f,%.1f H%.1f Z" % (
        x0,
        y,
        x0 + w - r,
        x0 + w,
        y,
        x0 + w,
        y + r,
        y + h - r,
        x0 + w,
        y + h,
        x0 + w - r,
        y + h,
        x0,
    )


def bar_v(x, y0, w, h, r=4):
    """Вертикальный столбец от базовой линии y0 вверх, скруглена только вершина."""
    r = max(0.0, min(r, w / 2.0, h / 2.0))
    top = y0 - h
    return "M%.1f,%.1f V%.1f Q%.1f,%.1f %.1f,%.1f H%.1f Q%.1f,%.1f %.1f,%.1f V%.1f Z" % (
        x,
        y0,
        top + r,
        x,
        top,
        x + r,
        top,
        x + w - r,
        x + w,
        top,
        x + w,
        top + r,
        y0,
    )


def legend(items):
    out = ['<div class="legend">']
    for label, color, kind in items:
        out.append(
            '<span><i class="sw %s%s"></i>%s</span>' % (SWATCH[color], " line" if kind == "line" else "", esc(label))
        )
    out.append("</div>")
    return "".join(out)


# ----------------------------------------------------------------- графики


def forest(rows, series_names, title, width=760):
    """rows: [(label, [(value, (lo, hi), tip) | None per series])]. Ось X общая (одна шкала)."""
    vals = [c for _, cells in rows for c in cells if c and c[0] is not None]
    if not vals:
        return ""
    lo = min(min(c[1][0] if c[1][0] is not None else c[0] for c in vals), min(c[0] for c in vals))
    lo = max(0.0, math.floor((lo - 0.02) * 20) / 20.0)
    hi = 1.0
    left, right, top, row_h = 210, 18, 10, 30
    plot_w = width - left - right
    height = top + row_h * len(rows) + 34
    sx = lambda v: left + (v - lo) / (hi - lo) * plot_w  # noqa: E731
    out = ['<svg viewBox="0 0 %d %d" role="img" aria-label="%s">' % (width, height, esc(title))]
    for t in nice_ticks(lo, hi, 6):
        x = sx(t)
        out.append('<line class="grid" x1="%.1f" x2="%.1f" y1="%d" y2="%d"/>' % (x, x, top, height - 24))
        out.append('<text x="%.1f" y="%d" text-anchor="middle">%s</text>' % (x, height - 8, f(t, 2)))
    n = len(series_names)
    for i, (label, cells) in enumerate(rows):
        yc = top + i * row_h + row_h / 2.0
        if i % 2 == 0:
            out.append(
                '<rect x="0" y="%.1f" width="%d" height="%d" fill="var(--grid)" opacity=".35" rx="6"/>'
                % (yc - row_h / 2.0 + 1, width, row_h - 2)
            )
        out.append('<text class="lbl" x="%d" y="%.1f" dominant-baseline="middle">%s</text>' % (8, yc, esc(label)))
        for j, cell in enumerate(cells):
            if not cell or cell[0] is None:
                continue
            v, (clo, chi), tip = cell
            y = yc + (j - (n - 1) / 2.0) * 9
            color = SERIES[j % len(SERIES)]
            out.append('<g class="mark" data-tip="%s">' % esc(tip))
            out.append(
                '<rect x="%.1f" y="%.1f" width="%.1f" height="12" fill="transparent"/>'
                % (
                    sx(clo if clo is not None else v) - 4,
                    y - 6,
                    max(10.0, sx(chi if chi is not None else v) - sx(clo if clo is not None else v) + 8),
                )
            )
            if clo is not None:
                out.append(
                    '<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="2" '
                    'stroke-linecap="round"/>' % (sx(max(lo, clo)), sx(chi), y, y, color)
                )
            out.append(
                '<circle cx="%.1f" cy="%.1f" r="4.5" fill="%s" stroke="var(--surface)" stroke-width="2"/>'
                % (sx(v), y, color)
            )
            out.append("</g>")
    out.append("</svg>")
    return "".join(out)


def hbars(items, unit, title, color="var(--s1)", width=760, digits=1):
    """items: [(label, value, tip)]. Одна серия: легенда не нужна, название — в заголовке."""
    if not items:
        return ""
    vmax = max(v for _, v, _ in items) or 1.0
    left, right, top, row_h, bh = 230, 70, 6, 26, 14
    plot_w = width - left - right
    height = top + row_h * len(items) + 8
    out = ['<svg viewBox="0 0 %d %d" role="img" aria-label="%s">' % (width, height, esc(title))]
    out.append('<line class="axis" x1="%d" x2="%d" y1="%d" y2="%d"/>' % (left, left, top, height - 6))
    for i, (label, v, tip) in enumerate(items):
        y = top + i * row_h + (row_h - bh) / 2.0
        w = max(1.5, v / vmax * plot_w)
        out.append(
            '<text class="lbl" x="%d" y="%.1f" dominant-baseline="middle">%s</text>' % (8, y + bh / 2.0, esc(label))
        )
        out.append('<path class="mark" data-tip="%s" d="%s" fill="%s"/>' % (esc(tip), bar_h(left, y, w, bh), color))
        out.append(
            '<text x="%.1f" y="%.1f" dominant-baseline="middle">%s %s</text>'
            % (left + w + 6, y + bh / 2.0, f(v, digits), esc(unit))
        )
    out.append("</svg>")
    return "".join(out)


def depth_chart(depth, width=760):
    hist, pois, nb = depth["hist"], depth["poisson"], depth.get("negbin")
    ymax = max([p for _, p in hist] + [p for _, p in pois] + ([p for _, p in nb] if nb else [])) * 1.08
    left, right, top, bottom = 52, 16, 10, 34
    plot_w, plot_h = width - left - right, 250
    height = top + plot_h + bottom
    dmax = hist[-1][0]
    bw = plot_w / float(dmax + 1)
    sx = lambda d: left + d * bw  # noqa: E731
    sy = lambda p: top + plot_h - p / ymax * plot_h  # noqa: E731
    out = ['<svg viewBox="0 0 %d %d" role="img" aria-label="Распределение глубины">' % (width, height)]
    for t in nice_ticks(0, ymax, 4):
        out.append('<line class="grid" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (left, width - right, sy(t), sy(t)))
        out.append(
            '<text x="%d" y="%.1f" text-anchor="end" dominant-baseline="middle">%s</text>'
            % (left - 6, sy(t), pct(t, 1))
        )
    for t in nice_ticks(0, dmax, 8):
        out.append('<text x="%.1f" y="%d" text-anchor="middle">%dx</text>' % (sx(t) + bw / 2.0, height - 12, t))
    for d, p in hist:
        h = p / ymax * plot_h
        if h <= 0:
            continue
        out.append(
            '<path class="mark" data-tip="%s" d="%s" fill="var(--s1)" opacity=".85"/>'
            % (
                esc("глубина %dx: %s позиций" % (d, pct(p, 2))),
                bar_v(sx(d) + 1, top + plot_h, max(1.0, bw - 2), h, r=min(4, (bw - 2) / 2.0)),
            )
        )
    for series, color in ((pois, "var(--s2)"), (nb, "var(--s3)")):
        if not series:
            continue
        pts = " ".join("%.1f,%.1f" % (sx(d) + bw / 2.0, sy(p)) for d, p in series)
        out.append(
            '<polyline points="%s" fill="none" stroke="%s" stroke-width="2" stroke-linejoin="round"/>' % (pts, color)
        )
    out.append(
        '<line class="axis" x1="%d" x2="%d" y1="%d" y2="%d"/>' % (left, width - right, top + plot_h, top + plot_h)
    )
    out.append("</svg>")
    return "".join(out)


def grouped_bars(classes, series, width=760):
    """series: [(name, {class: share}, {class: count})]; доли внутри серии, одна шкала."""
    ymax = max(v for _, shares, _ in series for v in shares.values()) * 1.15 or 1.0
    left, right, top, bottom = 52, 16, 10, 34
    plot_w, plot_h = width - left - right, 220
    height = top + plot_h + bottom
    group_w = plot_w / float(len(classes))
    bw = min(28.0, (group_w - 16) / len(series))
    sy = lambda p: top + plot_h - p / ymax * plot_h  # noqa: E731
    out = ['<svg viewBox="0 0 %d %d" role="img" aria-label="Спектр замен">' % (width, height)]
    for t in nice_ticks(0, ymax, 4):
        out.append('<line class="grid" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (left, width - right, sy(t), sy(t)))
        out.append(
            '<text x="%d" y="%.1f" text-anchor="end" dominant-baseline="middle">%s</text>'
            % (left - 6, sy(t), pct(t, 0))
        )
    for i, cls in enumerate(classes):
        gx = left + i * group_w + (group_w - bw * len(series) - 2 * (len(series) - 1)) / 2.0
        for j, (name, shares, counts) in enumerate(series):
            v = shares.get(cls, 0.0)
            h = v / ymax * plot_h
            x = gx + j * (bw + 2)
            if h > 0:
                out.append(
                    '<path class="mark" data-tip="%s" d="%s" fill="%s"/>'
                    % (
                        esc("%s, %s: %s (%d)" % (name, cls, pct(v, 1), counts.get(cls, 0))),
                        bar_v(x, top + plot_h, bw, h),
                        SERIES[j],
                    )
                )
        out.append(
            '<text class="lbl" x="%.1f" y="%d" text-anchor="middle">%s</text>'
            % (left + i * group_w + group_w / 2.0, height - 12, esc(cls))
        )
    out.append(
        '<line class="axis" x1="%d" x2="%d" y1="%d" y2="%d"/>' % (left, width - right, top + plot_h, top + plot_h)
    )
    out.append("</svg>")
    return "".join(out)


# ----------------------------------------------------------------- таблицы


def table(header, rows, num_cols=()):
    out = ['<div class="scroll" tabindex="0" role="region" aria-label="Таблица"><table><thead><tr>']
    out += [
        '<th class="num">%s</th>' % esc(h) if i in num_cols else "<th>%s</th>" % esc(h) for i, h in enumerate(header)
    ]
    out.append("</tr></thead><tbody>")
    for r in rows:
        out.append(
            "<tr>"
            + "".join('<td class="num">%s</td>' % c if i in num_cols else "<td>%s</td>" % c for i, c in enumerate(r))
            + "</tr>"
        )
    out.append("</tbody></table></div>")
    return "".join(out)


def ci_txt(v, c, d=4):
    if v is None:
        return "–"
    if not c or c[0] is None:
        return f(v, d)
    return '%s <span class="note">[%s; %s]</span>' % (f(v, d), f(c[0], d), f(c[1], d))


STRATA_RU = {
    "*": "весь регион",
    "not_in_all_difficult": "вне сложных участков",
    "all_difficult": "все сложные участки",
    "homopolymers_ge7": "гомополимеры ≥ 7 п.н.",
    "tandem_repeats": "тандемные повторы",
    "low_mappability": "низкая картируемость",
    "segdups": "сегментные дупликации",
    "gc_lt25_or_gt65": "GC < 25% или > 65%",
    "refseq_cds": "кодирующие экзоны RefSeq",
}
STRATA_ORDER = [
    "*",
    "not_in_all_difficult",
    "all_difficult",
    "homopolymers_ge7",
    "tandem_repeats",
    "low_mappability",
    "segdups",
    "gc_lt25_or_gt65",
    "refseq_cds",
]


def step_label(name):
    labels = {
        "fastp": "fastp",
        "bwa_mem2_index": "bwa-mem2 index",
        "bwa_mem2_mem": "bwa-mem2 mem | fixmate",
        "samtools_sort": "samtools sort",
        "samtools_markdup": "samtools markdup",
        "samtools_qc": "samtools QC",
        "bcftools_call": "bcftools mpileup | call",
        "bcftools_filter": "bcftools norm | filter",
        "bcftools_stats": "bcftools stats",
    }
    if name.startswith("happy_"):
        return "hap.py · " + name[len("happy_") :]
    return labels.get(name, name)


# ----------------------------------------------------------------- страница


def render(rep):
    bench = rep.get("benchmark", {})
    names = list(bench)
    primary = names[0] if names else None

    def pass_row(name, vtype):
        return next((r for r in bench[name]["summary"] if r["type"] == vtype and r["filter"] == "PASS"), None)

    aln, calls, reads, tot = rep["alignment"], rep["calls"], rep["reads"], rep["totals"]
    qc = rep.get("qc_pass")
    badge = (
        '<span class="badge ok">✓ порог качества пройден</span>'
        if qc
        else '<span class="badge fail">✕ порог качества не пройден</span>'
        if qc is False
        else ""
    )
    out = [
        '<!doctype html><html lang="ru"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" content="%s">' % CSP,
        '<meta name="color-scheme" content="light dark">',
        "<title>%s mini-WGS report</title><style>%s</style></head><body><main>" % (esc(rep["sample"]), CSS),
    ]
    out.append(
        "<header><h1>%s · mini-WGS %s</h1><p>FASTQ → fastp → bwa-mem2 → samtools → bcftools → hap.py · "
        "потоков %s · профиль mpileup <code>%s</code> · %s</p></header>"
        % (
            esc(rep["sample"]),
            badge,
            esc(rep.get("threads")),
            esc(rep.get("mpileup_profile") or "default"),
            esc(rep.get("generated_utc")),
        )
    )

    # плитки
    tiles = []
    if primary:
        for vtype in ("SNP", "INDEL"):
            r = pass_row(primary, vtype)
            if r:
                tiles.append(
                    (
                        vtype + " F1 · " + primary,
                        f(r["f1"], 4),
                        "95%% ДИ %s–%s" % (f(r["f1_ci"][0], 3), f(r["f1_ci"][1], 3)),
                    )
                )
    tiles.append(("средняя глубина", "%sx" % f(aln.get("mean_depth"), 1), "без дубликатов"))
    tiles.append(("время прогона", "%s с" % f(tot["wall_s"], 0), "CPU %s с" % f(tot["cpu_s"], 0)))
    tiles.append(("пик памяти шага", "%s МБ" % f(tot["max_peak_rss_mb"], 0), "RSS по дереву процессов"))
    out.append(
        '<div class="tiles">'
        + "".join(
            '<div class="tile"><div class="k">%s</div><div class="v">%s</div><div class="s">%s</div></div>'
            % (esc(k), esc(v), esc(s))
            for k, v, s in tiles
        )
        + "</div>"
    )

    # сверка с эталонами
    if names:
        out.append(
            '<section><h2>Точность против эталонов GIAB</h2><p class="lead">F1 с 95% доверительным '
            "интервалом по стратификациям GIAB v3.6, только PASS. Эталон v5.0q построен по сборке генома "
            "HG002 (T2T-Q100) и включает сложные участки, которых нет в v4.2.1. Поэтому на нём точность "
            "ниже, и это честнее.</p>"
        )
        out.append(legend([(n, SERIES[i], "dot") for i, n in enumerate(names)]))
        for vtype in ("SNP", "INDEL"):
            rows = []
            for key in STRATA_ORDER:
                cells, any_cell = [], False
                for n in names:
                    if key == "*":
                        r = pass_row(n, vtype)
                    else:
                        r = next((x for x in bench[n]["strata"] if x["subset"] == key and x["type"] == vtype), None)
                    if r and r["f1"] is not None and (r["truth_total"] or r["fp"]):
                        any_cell = True
                        tip = "%s · %s · %s\nF1 %s [%s; %s]\nrecall %s, precision %s\nTP %d · FN %d · FP %d" % (
                            n,
                            vtype,
                            STRATA_RU.get(key, key),
                            f(r["f1"], 4),
                            f(r["f1_ci"][0], 4),
                            f(r["f1_ci"][1], 4),
                            f(r["recall"], 4),
                            f(r["precision"], 4),
                            r["tp"],
                            r["fn"],
                            r["fp"],
                        )
                        cells.append((r["f1"], r["f1_ci"], tip))
                    else:
                        cells.append(None)
                if any_cell:
                    rows.append((STRATA_RU.get(key, key), cells))
            out.append("<h3>%s</h3>" % ("SNV" if vtype == "SNP" else "Инделы"))
            out.append(forest(rows, names, "F1 по стратам, " + vtype))
        for n in names:
            b = bench[n]
            out.append("<details><summary>Таблица: %s, все строки hap.py summary</summary>" % esc(n))
            out.append(
                table(
                    [
                        "тип",
                        "фильтр",
                        "в эталоне",
                        "TP",
                        "FN",
                        "FP",
                        "recall [95% ДИ]",
                        "precision [95% ДИ]",
                        "F1 [95% ДИ]",
                    ],
                    [
                        [
                            esc(r["type"]),
                            esc(r["filter"]),
                            r["truth_total"],
                            r["tp"],
                            r["fn"],
                            r["fp"],
                            ci_txt(r["recall"], r["recall_ci"]),
                            ci_txt(r["precision"], r["precision_ci"]),
                            ci_txt(r["f1"], r["f1_ci"]),
                        ]
                        for r in b["summary"]
                    ],
                    num_cols=(2, 3, 4, 5),
                )
            )
            out.append(
                table(
                    ["страта", "тип", "в эталоне", "TP", "FN", "FP", "recall [95% ДИ]", "precision [95% ДИ]", "F1"],
                    [
                        [
                            esc(STRATA_RU.get(r["subset"], r["subset"])),
                            esc(r["type"]),
                            r["truth_total"],
                            r["tp"],
                            r["fn"],
                            r["fp"],
                            ci_txt(r["recall"], r["recall_ci"], 3),
                            ci_txt(r["precision"], r["precision_ci"], 3),
                            f(r["f1"], 3),
                        ]
                        for r in sorted(
                            b["strata"],
                            key=lambda x: (
                                STRATA_ORDER.index(x["subset"]) if x["subset"] in STRATA_ORDER else 99,
                                x["type"],
                            ),
                        )
                        if r["truth_total"] or r["fp"]
                    ],
                    num_cols=(2, 3, 4, 5),
                )
            )
            out.append("</details>")
        out.append("</section>")

    # спектр
    if primary:
        spec = bench[primary]["spectrum"]
        classes = ["C>A", "C>G", "C>T", "T>A", "T>C", "T>G"]
        series = []
        for lab, key in (("истинные (TP)", "TP"), ("ложные (FP)", "FP")):
            counts = spec.get(key, {})
            total = float(sum(counts.values())) or 1.0
            series.append((lab, {c: counts.get(c, 0) / total for c in classes}, counts))
        ox = bench[primary]["oxog"]
        out.append(
            '<section><h2>Спектр замен: истинные и ложные SNV</h2><p class="lead">Доли шести классов '
            "замен (на пиримидиновой цепи), эталон %s. Окисление гуанина до 8-oxoG при подготовке "
            "библиотеки даёт ложные G&gt;T, то есть избыток C&gt;A среди ложноположительных. Тест Фишера: "
            "C&gt;A среди FP %d из %d против %d из %d среди TP, p = %s.</p>"
            % (
                esc(primary),
                ox["fp_c2a"],
                ox["fp_total"],
                ox["tp_c2a"],
                ox["tp_total"],
                ("%.3g" % ox["fisher_p"]) if ox["fisher_p"] is not None else "–",
            )
        )
        out.append(legend([(s[0], SERIES[i], "box") for i, s in enumerate(series)]))
        out.append(grouped_bars(classes, series))
        out.append("<details><summary>Таблица спектра</summary>")
        out.append(
            table(
                ["класс"] + [s[0] for s in series],
                [[c] + ["%s (%d)" % (pct(s[1][c], 1), s[2].get(c, 0)) for s in series] for c in classes],
                num_cols=(1, 2),
            )
        )
        out.append("</details></section>")

    # глубина
    if aln.get("depth"):
        d = aln["depth"]
        out.append(
            '<section><h2>Распределение глубины покрытия</h2><p class="lead">Доля позиций с данной '
            "глубиной (без дубликатов) и две модели с тем же средним. Индекс дисперсии %s: у Пуассона он "
            "равен 1, у реальной библиотеки больше из-за GC-смещения и неравномерной амплификации. "
            "Отрицательное биномиальное описывает хвост низкой глубины заметно лучше.</p>" % f(d["dispersion_index"], 2)
        )
        items = [("наблюдаемая доля позиций", "var(--s1)", "box"), ("Пуассон", "var(--s2)", "line")]
        if d.get("negbin"):
            items.append(("отрицательное биномиальное", "var(--s3)", "line"))
        out.append(legend(items))
        out.append(depth_chart(d))
        out.append("<details><summary>Таблица: доля позиций с глубиной ниже порога</summary>")
        out.append(
            table(
                ["глубина <", "наблюдается", "Пуассон", "отр. биномиальное"],
                [
                    ["%dx" % t["lt"], pct(t["observed"], 3), pct(t["poisson"], 3), pct(t["negbin"], 3)]
                    for t in d["thresholds"]
                ],
                num_cols=(1, 2, 3),
            )
        )
        out.append("</details></section>")

    # ресурсы
    steps = rep.get("steps", [])
    if steps:
        out.append(
            '<section><h2>Время и память по шагам</h2><p class="lead">Замер bin/measure.py внутри '
            "каждого шага CWL. Пик памяти считается как максимум из крупнейшего процесса и суммы RSS по "
            "дереву процессов, поэтому конвейер <code>a | b</code> учтён целиком.</p>"
        )
        out.append("<h3>Время, с</h3>")
        out.append(
            hbars(
                [
                    (
                        step_label(s["step"]),
                        s["wall_s"],
                        "%s\nвремя %s с · CPU %s с · %s%%"
                        % (
                            step_label(s["step"]),
                            f(s["wall_s"], 2),
                            f(s["user_s"] + s["sys_s"], 2),
                            f(s["cpu_pct"], 0),
                        ),
                    )
                    for s in steps
                ],
                "с",
                "Время по шагам",
            )
        )
        out.append("<h3>Пик памяти, МБ</h3>")
        out.append(
            hbars(
                [
                    (
                        step_label(s["step"]),
                        s["peak_rss_mb"],
                        "%s\nпик %s МБ · крупнейший процесс %s МБ"
                        "\nрекомендуемый --mem %dM"
                        % (step_label(s["step"]), f(s["peak_rss_mb"], 0), f(s["max_rss_mb"], 0), s["suggested_mem_mb"]),
                    )
                    for s in steps
                ],
                "МБ",
                "Пик памяти по шагам",
                digits=0,
            )
        )
        out.append("<details><summary>Таблица ресурсов и рекомендации для Slurm</summary>")
        out.append(
            table(
                [
                    "шаг",
                    "время, с",
                    "CPU, с",
                    "CPU %",
                    "потоки",
                    "эффективность",
                    "пик RSS, МБ",
                    "крупнейший процесс, МБ",
                    "--mem",
                ],
                [
                    [
                        esc(step_label(s["step"])),
                        f(s["wall_s"], 2),
                        f(s["user_s"] + s["sys_s"], 2),
                        f(s["cpu_pct"], 0),
                        s.get("threads") or "–",
                        f(s.get("cpu_efficiency"), 2),
                        f(s["peak_rss_mb"], 0),
                        f(s["max_rss_mb"], 0),
                        "%dM" % s["suggested_mem_mb"],
                    ]
                    for s in steps
                ],
                num_cols=(1, 2, 3, 4, 5, 6, 7),
            )
        )
        out.append("</details>")
        sc = rep.get("scaling")
        if sc:
            out.append(
                '<p class="note">Нижняя оценка для генома 30x: ≈ %s CPU-часов, для 100 000 геномов ≈ %s млн '
                "CPU-часов (×%s по числу оснований, без индексации и hap.py; выравнивание на полный GRCh38 "
                "медленнее на рид).</p>"
                % (
                    f(sc["cpu_hours_per_30x_genome_lower_bound"], 0),
                    f(sc["cpu_hours_100k_genomes_lower_bound"] / 1e6, 1),
                    f(sc["factor"], 0),
                )
            )
        out.append("</section>")

    # QC и данные
    out.append("<section><h2>Контроль качества</h2>")
    if rep.get("checks"):
        out.append(
            table(
                ["проверка", "значение", "граница", "итог"],
                [
                    [
                        esc(c["name"]),
                        f(c["value"], 4),
                        "%s %s" % (esc(c["op"]), c["limit"]),
                        '<span class="ok-ink">✓ да</span>' if c["pass"] else '<span class="bad-ink">✕ нет</span>',
                    ]
                    for c in rep["checks"]
                ],
                num_cols=(1,),
            )
        )
    out.append(
        table(
            ["метрика", "значение"],
            [
                ["пар ридов до → после fastp", "%s → %s" % (reads["pairs_before"], reads["pairs_after"])],
                ["оснований Q30", "%s → %s" % (pct(reads["q30_before"], 2), pct(reads["q30_after"], 2))],
                [
                    "картировано / в правильных парах",
                    "%s %% / %s %%" % (f(aln.get("mapped_pct"), 2), f(aln.get("properly_paired_pct"), 2)),
                ],
                [
                    "дубликаты: всего / оптические / ПЦР",
                    "%s / %s / %s"
                    % (
                        pct(aln.get("dup_rate"), 2),
                        pct(aln.get("optical_dup_rate"), 2),
                        pct(aln.get("library_dup_rate"), 2),
                    ),
                ],
                ["длина вставки", "%s ± %s" % (f(aln.get("insert_size_mean"), 1), f(aln.get("insert_size_sd"), 1))],
                ["SNP / инделы (PASS)", "%s / %s" % (calls.get("snps"), calls.get("indels"))],
                ["Ti/Tv · het/hom", "%s · %s" % (f(calls.get("ts_tv"), 2), f(calls.get("het_hom_ratio"), 2))],
            ],
        )
    )
    out.append("</section>")

    out.append("<section><h2>Версии</h2>")
    out.append(table(["инструмент", "версия"], [[esc(k), esc(v)] for k, v in rep.get("versions", {}).items()]))
    out.append("</section>")
    out.append(
        "<footer>hg002-mini-wgs · отчёт собран из report.json скриптом scripts/render_html.py · "
        "данные GIAB/NIST и Google DeepVariant case study, публичные.</footer>"
    )
    out.append('</main><div id="tip" role="tooltip"></div><script>%s</script></body></html>' % JS)
    return "".join(out)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("report_json")
    p.add_argument("-o", "--output", default="-")
    a = p.parse_args(argv)
    with open(a.report_json, encoding="utf-8") as fh:
        page = render(json.load(fh))
    if a.output == "-":
        sys.stdout.write(page)
    else:
        with open(a.output, "w", encoding="utf-8") as fh:
            fh.write(page)
    return 0


if __name__ == "__main__":
    sys.exit(main())
