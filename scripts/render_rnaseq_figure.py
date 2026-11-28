#!/usr/bin/env python3
"""Рисунок RNA-seq против эталона ERCC (SVG, светлая и тёмная тема, широкий и узкий).

    python3 scripts/render_rnaseq_figure.py   # -> docs/assets/ercc[-narrow]-{light,dark}.svg

Слева — линейность: log2(фрагменты на килобазу) против log2(концентрации ERCC) во всех
шести образцах; у линейного метода наклон 1. Справа — точность кратности: log2(UHR/HBR)
каждого ERCC после поправки на долю мРНК против известного значения в подгруппах A–D.
Все точки берутся из docs/results/rnaseq/rnaseq.report.json, руками ничего не набирается.
"""

import json
import math
import os

from render_infographic import FONT, THEMES, rr, text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "assets")
REPORT = os.path.join(ROOT, "docs", "results", "rnaseq", "rnaseq.report.json")
MIN_FIT = 10  # как в rnaseq_report.MIN_FIT_COUNT
SUBGROUPS = (("A", "4 : 1"), ("B", "1 : 1"), ("C", "2 : 3"), ("D", "1 : 2"))


def colors(t):
    return {"UHR": t["accent"], "HBR": t["accent2"]}


def group_fit(rep, group):
    """Средние наклон и свободный член по репликам группы (для линии на графике)."""
    ds = [s["ercc_dose_response"] for s in rep["samples"] if s["group"] == group]
    return sum(d["slope"] for d in ds) / len(ds), sum(d["intercept"] for d in ds) / len(ds)


def dose_panel(rep, t, x0, y0, w, h, compact=False):
    """Линейность: точки всех образцов и линии средних по группам."""
    col = colors(t)
    pts = []
    for s in rep["samples"]:
        for _, conc, n, length in s["ercc_dose_response"]["points"]:
            if n > 0:
                pts.append((s["group"], math.log2(conc), math.log2(n / (length / 1000.0)), n >= MIN_FIT))
    xs, ys = [p[1] for p in pts], [p[2] for p in pts]
    xlo, xhi = math.floor(min(xs)) - 1, math.ceil(max(xs)) + 1
    ylo, yhi = math.floor(min(ys)) - 1, math.ceil(max(ys)) + 1

    def sx(v):
        return x0 + (v - xlo) / float(xhi - xlo) * w

    def sy(v):
        return y0 + h - (v - ylo) / float(yhi - ylo) * h

    out = [rr(x0, y0, w, h, t["panel"], t["line"], r=8)]
    step = 4 if xhi - xlo > 12 else 2
    for v in range(int(xlo) + (-int(xlo)) % step, int(xhi) + 1, step):
        out.append(
            '<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="%s"/>' % (sx(v), sx(v), y0, y0 + h, t["line"])
        )
        out.append(text(sx(v), y0 + h + 17, "%d" % v, 11.5, "ink2", anchor="middle", t=t))
    for v in range(int(ylo) + (-int(ylo)) % step, int(yhi) + 1, step):
        out.append(
            '<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="%s"/>' % (x0, x0 + w, sy(v), sy(v), t["line"])
        )
        out.append(text(x0 - 6, sy(v) + 4, "%d" % v, 11.5, "ink2", anchor="end", t=t))
    for group, x, y, fitted in pts:
        if fitted:
            out.append(
                '<circle cx="%.1f" cy="%.1f" r="3.2" fill="%s" fill-opacity="0.55"/>' % (sx(x), sy(y), col[group])
            )
        else:  # обнаружен, но < MIN_FIT фрагментов: в модель не входит
            out.append(
                '<circle cx="%.1f" cy="%.1f" r="3" fill="none" stroke="%s" stroke-opacity="0.7"/>'
                % (sx(x), sy(y), col[group])
            )
    for group in ("UHR", "HBR"):
        slope, icpt = group_fit(rep, group)
        fx = [p[1] for p in pts if p[0] == group and p[3]]
        a, b = min(fx), max(fx)
        out.append(
            '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="2.5"/>'
            % (sx(a), sy(icpt + slope * a), sx(b), sy(icpt + slope * b), col[group])
        )
    out.append(
        text(x0 + w / 2.0, y0 + h + 36, "log2 концентрации ERCC, аттомоль/мкл", 12, "ink2", anchor="middle", t=t)
    )
    out.append(
        '<text x="%.1f" y="%.1f" font-family="%s" font-size="12" fill="%s" text-anchor="middle" '
        'transform="rotate(-90 %.1f %.1f)">log2 фрагментов на килобазу</text>'
        % (x0 - 34, y0 + h / 2.0, FONT, t["ink2"], x0 - 34, y0 + h / 2.0)
    )
    slopes = [s["ercc_dose_response"]["slope"] for s in rep["samples"]]
    r2 = [s["ercc_dose_response"]["r2"] for s in rep["samples"]]
    note = "наклон %.2f–%.2f · R² ≥ %.3f" % (min(slopes), max(slopes), min(r2))
    out.append(rr(x0 + 10, y0 + 10, 232 if not compact else 214, 26, t["bg"], t["line"], r=6))
    out.append(text(x0 + 20, y0 + 28, note, 12.5 if not compact else 12, "ink", 600, t=t))
    return out


def fold_panel(rep, t, x0, y0, w, h, compact=False):
    """Точность кратности: log2(UHR/HBR) после поправки против ожидаемого по подгруппам."""
    fold = rep["ercc_fold_change"]
    rows = fold["rows"]
    lo, hi = -2.0, 3.0

    def sy(v):
        return y0 + h - (v - lo) / (hi - lo) * h

    out = [rr(x0, y0, w, h, t["panel"], t["line"], r=8)]
    for v in (-2, -1, 0, 1, 2, 3):
        out.append(
            '<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="%s"/>' % (x0, x0 + w, sy(v), sy(v), t["line"])
        )
        out.append(text(x0 - 6, sy(v) + 4, "%d" % v, 11.5, "ink2", anchor="end", t=t))
    slot = w / float(len(SUBGROUPS))
    for i, (g, ratio) in enumerate(SUBGROUPS):
        cx = x0 + slot * (i + 0.5)
        sub = [r for r in rows if r["subgroup"] == g]
        info = fold["subgroups"].get(g)
        if not sub or not info:
            continue
        exp = info["expected_log2"]
        out.append(
            '<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="2" stroke-dasharray="6 4"/>'
            % (cx - slot * 0.38, cx + slot * 0.38, sy(exp), sy(exp), t["ink"])
        )
        for j, r in enumerate(sorted(sub, key=lambda r: r["ercc"])):
            dx = (j - (len(sub) - 1) / 2.0) * min(7.0, slot * 0.6 / max(1, len(sub)))
            out.append(
                '<circle cx="%.1f" cy="%.1f" r="3.6" fill="%s" fill-opacity="0.75"/>'
                % (cx + dx, sy(max(lo, min(hi, r["adjusted"]))), t["accent3"])
            )
        med = info["median_adjusted"]
        out.append(
            '<rect x="%.1f" y="%.1f" width="%.1f" height="3" rx="1.5" fill="%s"/>'
            % (cx - slot * 0.3, sy(med) - 1.5, slot * 0.6, t["accent3"])
        )
        out.append(text(cx, y0 + h + 17, "%s · %s" % (g, ratio), 12, "ink", 600, anchor="middle", t=t))
        out.append(
            text(cx, y0 + h + 33, "смещ. %+.2f" % info["bias"], 11.5, "ink2", anchor="middle", t=t).replace("+", "+")
        )
    out.append(
        '<text x="%.1f" y="%.1f" font-family="%s" font-size="12" fill="%s" text-anchor="middle" '
        'transform="rotate(-90 %.1f %.1f)">log2(UHR / HBR) после поправки</text>'
        % (x0 - 30, y0 + h / 2.0, FONT, t["ink2"], x0 - 30, y0 + h / 2.0)
    )
    note = "r = %.3f · RMSE %.2f" % (fold["pearson"], fold["rmse"])
    out.append(rr(x0 + 10, y0 + 10, 170 if not compact else 160, 26, t["bg"], t["line"], r=6))
    out.append(text(x0 + 20, y0 + 28, note, 12.5 if not compact else 12, "ink", 600, t=t))
    return out


def legend(t, x, y, size=12.5):
    col = colors(t)
    out, lx = [], x
    for label, color, filled in (
        ("UHR + Mix 1", col["UHR"], True),
        ("HBR + Mix 2", col["HBR"], True),
        ("< %d фрагм., вне модели" % MIN_FIT, t["ink2"], False),
        ("ERCC: кратность", t["accent3"], True),
    ):
        if filled:
            out.append('<circle cx="%.1f" cy="%.1f" r="5" fill="%s"/>' % (lx + 5, y - 4, color))
        else:
            out.append('<circle cx="%.1f" cy="%.1f" r="4.5" fill="none" stroke="%s"/>' % (lx + 5, y - 4, color))
        out.append(text(lx + 15, y + 1, label, size, "ink", t=t))
        lx += 26 + len(label) * size * 0.52
    return out


def ercc_svg(rep, theme):
    t = THEMES[theme]
    fold = rep["ercc_fold_change"]
    W, H = 1200, 580
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" '
        'aria-label="RNA-seq против эталона ERCC: линейность и точность кратности">' % (W, H, W, H)
    ]
    out.append(rr(0, 0, W, H, t["bg"], r=16))
    out.append(text(32, 46, "RNA-seq против эталона ERCC: линейность и точность кратности", 22, "ink", 700, t=t))
    out.append(
        text(
            32,
            72,
            "92 синтетических транскрипта известной концентрации; UHR + ERCC Mix 1 и HBR + Mix 2, по 3 реплики.",
            13.5,
            "ink2",
            t=t,
        )
    )
    out.append(
        text(
            32,
            92,
            "Справа отношения исправлены на разную долю мРНК в образцах: сдвиг ×%.2f оценён по подгруппе B (1 : 1)."
            % fold["offset_ratio"],
            13.5,
            "ink2",
            t=t,
        )
    )
    out += legend(t, 32, 122)
    out += dose_panel(rep, t, 96, 150, 560, 330)
    out += fold_panel(rep, t, 760, 150, 408, 330)
    out.append(
        text(
            32,
            H - 18,
            "Пунктир — известное log2(Mix 1 / Mix 2), полоса — медиана. Данные: docs/results/rnaseq/rnaseq.report.json",
            11.5,
            "ink2",
            t=t,
        )
    )
    out.append("</svg>")
    return "\n".join(out)


def ercc_narrow_svg(rep, theme):
    t = THEMES[theme]
    W, H = 420, 900
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" '
        'aria-label="RNA-seq против эталона ERCC: линейность и точность кратности">' % (W, H, W, H)
    ]
    out.append(rr(0, 0, W, H, t["bg"], r=14))
    out.append(text(16, 34, "RNA-seq против эталона ERCC", 18, "ink", 700, t=t))
    out.append(text(16, 56, "UHR + Mix 1 и HBR + Mix 2, по 3 реплики", 12.5, "ink2", t=t))
    col = colors(t)
    lx = 16
    for label, color in (("UHR", col["UHR"]), ("HBR", col["HBR"]), ("ERCC: кратность", t["accent3"])):
        out.append('<circle cx="%.1f" cy="76" r="5" fill="%s"/>' % (lx + 5, color))
        out.append(text(lx + 15, 81, label, 12.5, "ink", t=t))
        lx += 30 + len(label) * 7.2
    out.append(text(16, 112, "Линейность", 15, "ink", 700, t=t))
    out += dose_panel(rep, t, 60, 124, 340, 300, compact=True)
    out.append(text(16, 512, "Точность кратности по подгруппам", 15, "ink", 700, t=t))
    out += fold_panel(rep, t, 60, 524, 340, 300, compact=True)
    out.append(text(16, H - 14, "Пунктир — известное значение, полоса — медиана", 11.5, "ink2", t=t))
    out.append("</svg>")
    return "\n".join(out)


def main():
    with open(REPORT, encoding="utf-8") as fh:
        rep = json.load(fh)
    os.makedirs(OUT, exist_ok=True)
    for theme in THEMES:
        for name, svg in (("ercc", ercc_svg(rep, theme)), ("ercc-narrow", ercc_narrow_svg(rep, theme))):
            with open(os.path.join(OUT, "%s-%s.svg" % (name, theme)), "w", encoding="utf-8") as fh:
                fh.write(svg + "\n")
    print("written: docs/assets/ercc[-narrow]-{light,dark}.svg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
