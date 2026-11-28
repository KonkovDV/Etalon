#!/usr/bin/env python3
"""Рисунок «точность от глубины» (SVG, светлая и тёмная тема, широкий и узкий).

    python3 scripts/render_depth_figure.py   # -> docs/assets/depth[-narrow]-{light,dark}.svg

Три панели по одной серии прореживания (зерно 1): F1 hap.py на GIAB v5.0q для трёх
вызывателей, F по формуле патента RU 2846268 на v4.2.1 с порогом 99,9 % и доля
эталонных вариантов, которая вообще вошла в знаменатель F. Данные — только из
docs/results/depth/curve.json.
"""

import json
import math
import os

from render_infographic import THEMES, rr, text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "assets")
CURVE = os.path.join(ROOT, "docs", "results", "depth", "curve.json")
CALLERS = (("bcftools", "bcftools"), ("strelka2", "Strelka2"), ("deepvariant", "DeepVariant"))
F1_TRUTH, F_TRUTH = "giab_v5.0q", "giab_v4.2.1"


def colors(t):
    return {"bcftools": t["ink2"], "strelka2": t["accent"], "deepvariant": t["accent2"]}


def series(points, caller, value):
    pts = sorted((p for p in points if p["seed"] == 1 and caller in p["callers"]), key=lambda p: p["mean_depth"])
    return [(p["mean_depth"], value(p["callers"][caller])) for p in pts]


def panel(t, x0, y0, w, h, xmax, ylo, yhi, yticks, yfmt, lines, title, threshold=None, compact=False):
    """lines: [(points, color, dashed)]; points: [(x, y)]."""

    def sx(v):
        return x0 + v / float(xmax) * w

    def sy(v):
        return y0 + h - (v - ylo) / float(yhi - ylo) * h

    out = [text(x0, y0 - 12, title, 13.5 if compact else 14, "ink", 700, t=t)]
    out.append(rr(x0, y0, w, h, t["panel"], t["line"], r=8))
    for v in yticks:
        out.append(
            '<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="%s"/>' % (x0, x0 + w, sy(v), sy(v), t["line"])
        )
        out.append(text(x0 - 6, sy(v) + 4, yfmt(v), 11, "ink2", anchor="end", t=t))
    for v in range(0, int(xmax) + 1, 10):
        out.append(text(sx(v), y0 + h + 16, "%dx" % v, 11, "ink2", anchor="middle", t=t))
    if threshold is not None:
        out.append(
            '<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="1.5" stroke-dasharray="5 4"/>'
            % (x0, x0 + w, sy(threshold), sy(threshold), t["ink"])
        )
        out.append(text(x0 + w - 6, sy(threshold) - 6, "порог 99,9 %", 11, "ink", 600, anchor="end", t=t))
    for pts, color, dashed in lines:
        pts = [(x, max(ylo, min(yhi, y))) for x, y in pts if y is not None]
        if len(pts) > 1:
            out.append(
                '<polyline fill="none" stroke="%s" stroke-width="2.2"%s points="%s"/>'
                % (
                    color,
                    ' stroke-dasharray="6 4"' if dashed else "",
                    " ".join("%.1f,%.1f" % (sx(x), sy(y)) for x, y in pts),
                )
            )
        for x, y in pts:
            out.append(
                '<circle cx="%.1f" cy="%.1f" r="3.4" fill="%s" stroke="%s" stroke-width="1.5"/>'
                % (sx(x), sy(y), t["bg"] if dashed else color, color)
            )
    return out


def ranges(points):
    xmax = 10 * math.ceil(max(p["mean_depth"] for p in points) / 10.0)
    f1 = [
        v
        for c, _ in CALLERS
        for _, v in series(points, c, lambda e: min(e[F1_TRUTH]["SNP"]["f1"], e[F1_TRUTH]["INDEL"]["f1"]))
    ]
    f1_lo = math.floor(min(f1) * 10) / 10.0
    pf = [v for c, _ in CALLERS for _, v in series(points, c, lambda e: e[F_TRUTH]["patent"]["f"]) if v is not None]
    pf_lo = math.floor(min(pf) * 1000) / 1000.0
    return xmax, f1_lo, min(pf_lo, 0.998)


def lines_for(points, t):
    col = colors(t)
    f1 = []
    for c, _ in CALLERS:
        f1.append((series(points, c, lambda e: e[F1_TRUTH]["SNP"]["f1"]), col[c], False))
        f1.append((series(points, c, lambda e: e[F1_TRUTH]["INDEL"]["f1"]), col[c], True))
    pf = [(series(points, c, lambda e: 100 * (e[F_TRUTH]["patent"]["f"] or 0)), col[c], False) for c, _ in CALLERS]
    share = [
        (series(points, c, lambda e: 100 * (e[F_TRUTH]["patent"]["truth_in_denominator_share"] or 0)), col[c], False)
        for c, _ in CALLERS
    ]
    return f1, pf, share


def legend(t, x, y, size=12.5):
    col = colors(t)
    out, lx = [], x
    for c, label in CALLERS:
        out.append('<circle cx="%.1f" cy="%.1f" r="5" fill="%s"/>' % (lx + 5, y - 4, col[c]))
        out.append(text(lx + 15, y + 1, label, size, "ink", t=t))
        lx += 30 + len(label) * size * 0.55
    out.append(
        '<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="2.2"/>'
        % (lx, lx + 22, y - 4, y - 4, t["ink"])
    )
    out.append(text(lx + 28, y + 1, "SNV", size, "ink", t=t))
    lx += 70
    out.append(
        '<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="2.2" stroke-dasharray="6 4"/>'
        % (lx, lx + 22, y - 4, y - 4, t["ink"])
    )
    out.append(text(lx + 28, y + 1, "инделы", size, "ink", t=t))
    return out


def ticks(lo, hi, step):
    n = int(round((hi - lo) / step))
    return [lo + i * step for i in range(n + 1)]


def depth_svg(res, theme):
    t = THEMES[theme]
    pts = res["points"]
    xmax, f1_lo, pf_lo = ranges(pts)
    f1, pf, share = lines_for(pts, t)
    W, H = 1200, 560
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" '
        'aria-label="Точность от глубины: F1 по GA4GH и F по формуле патента">' % (W, H, W, H)
    ]
    out.append(rr(0, 0, W, H, t["bg"], r=16))
    out.append(text(32, 46, "Точность от глубины: F1 по GA4GH и F по формуле патента", 22, "ink", 700, t=t))
    out.append(
        text(
            32,
            72,
            "HG002, chr20, пары ридов прорежены до 5–35x (зерно 1). F1 — на GIAB v5.0q; F и доля эталона в её "
            "знаменателе — на v4.2.1, ближе всего к эталонному набору патента.",
            13.5,
            "ink2",
            t=t,
        )
    )
    out += legend(t, 32, 102)
    out += panel(
        t, 92, 150, 300, 320, xmax, f1_lo, 1.0, ticks(f1_lo, 1.0, 0.1), lambda v: "%.1f" % v, f1, "F1, GIAB v5.0q"
    )
    out += panel(
        t,
        478,
        150,
        300,
        320,
        xmax,
        100 * pf_lo,
        100.0,
        ticks(100 * pf_lo, 100.0, 0.1),
        lambda v: "%.1f" % v,
        pf,
        "F по патенту, %",
        threshold=99.9,
    )
    out += panel(
        t,
        864,
        150,
        300,
        320,
        xmax,
        0.0,
        100.0,
        ticks(0, 100, 25),
        lambda v: "%d %%" % v,
        share,
        "эталон в знаменателе F",
    )
    out.append(
        text(
            32,
            H - 18,
            "Глубина — средняя по выравниваниям без дубликатов. Данные: docs/results/depth/curve.json",
            11.5,
            "ink2",
            t=t,
        )
    )
    out.append("</svg>")
    return "\n".join(out)


def depth_narrow_svg(res, theme):
    t = THEMES[theme]
    pts = res["points"]
    xmax, f1_lo, pf_lo = ranges(pts)
    f1, pf, share = lines_for(pts, t)
    W, H = 420, 1040
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" '
        'aria-label="Точность от глубины: F1 по GA4GH и F по формуле патента">' % (W, H, W, H)
    ]
    out.append(rr(0, 0, W, H, t["bg"], r=14))
    out.append(text(16, 34, "Точность от глубины", 18, "ink", 700, t=t))
    out.append(text(16, 56, "HG002, chr20, прореживание до 5–35x", 12.5, "ink2", t=t))
    col = colors(t)
    lx = 16
    for c, label in CALLERS:
        out.append('<circle cx="%.1f" cy="76" r="5" fill="%s"/>' % (lx + 5, col[c]))
        out.append(text(lx + 15, 81, label, 12.5, "ink", t=t))
        lx += 26 + len(label) * 7.0
    out.append(text(16, 102, "сплошная — SNV, пунктир — инделы", 12, "ink2", t=t))
    out += panel(
        t,
        64,
        140,
        336,
        230,
        xmax,
        f1_lo,
        1.0,
        ticks(f1_lo, 1.0, 0.1),
        lambda v: "%.1f" % v,
        f1,
        "F1, GIAB v5.0q",
        compact=True,
    )
    out += panel(
        t,
        64,
        440,
        336,
        230,
        xmax,
        100 * pf_lo,
        100.0,
        ticks(100 * pf_lo, 100.0, 0.1),
        lambda v: "%.1f" % v,
        pf,
        "F по патенту, %, v4.2.1",
        threshold=99.9,
        compact=True,
    )
    out += panel(
        t,
        64,
        740,
        336,
        230,
        xmax,
        0.0,
        100.0,
        ticks(0, 100, 25),
        lambda v: "%d %%" % v,
        share,
        "эталон в знаменателе F, v4.2.1",
        compact=True,
    )
    out.append(text(16, H - 14, "Данные: docs/results/depth/curve.json", 11.5, "ink2", t=t))
    out.append("</svg>")
    return "\n".join(out)


def main():
    with open(CURVE, encoding="utf-8") as fh:
        res = json.load(fh)
    os.makedirs(OUT, exist_ok=True)
    for theme in THEMES:
        for name, svg in (("depth", depth_svg(res, theme)), ("depth-narrow", depth_narrow_svg(res, theme))):
            with open(os.path.join(OUT, "%s-%s.svg" % (name, theme)), "w", encoding="utf-8") as fh:
                fh.write(svg + "\n")
    print("written: docs/assets/depth[-narrow]-{light,dark}.svg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
