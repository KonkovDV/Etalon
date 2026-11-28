#!/usr/bin/env python3
"""Инфографика для README из evidence.json и эталонного отчёта (SVG, светлая и тёмная).

    python3 scripts/render_infographic.py   # -> docs/assets/{pipeline,accuracy}[-narrow]-{light,dark}.svg

Числа на картинках не набираются руками: они берутся из тех же файлов, что и
README, поэтому расходиться им не с чего (см. scripts/lint_claims.py).
"""

import html
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "assets")

THEMES = {
    "light": {
        "bg": "#ffffff",
        "panel": "#f6f8fa",
        "line": "#d0d7de",
        "ink": "#1f2328",
        "ink2": "#59636e",
        "accent": "#257de0",
        "accent2": "#f47230",
        "accent3": "#00b894",
        "chip": "#eaf2fd",
        "good": "#1a7f37",
    },
    "dark": {
        "bg": "#0d1117",
        "panel": "#161b22",
        "line": "#30363d",
        "ink": "#e6edf3",
        "ink2": "#9198a1",
        "accent": "#338ced",
        "accent2": "#e76624",
        "accent3": "#00a888",
        "chip": "#112640",
        "good": "#3fb950",
    },
}
FONT = "system-ui,-apple-system,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif"


def esc(s):
    return html.escape(str(s), quote=True)


def text(x, y, s, size=14, fill="ink", weight=400, anchor="start", t=None, family=FONT):
    return (
        '<text x="%.1f" y="%.1f" font-family="%s" font-size="%s" font-weight="%d" fill="%s" '
        'text-anchor="%s">%s</text>' % (x, y, family, size, weight, t[fill], anchor, esc(s))
    )


def rr(x, y, w, h, fill, stroke=None, r=12, sw=1):
    return '<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="%d" fill="%s"%s/>' % (
        x,
        y,
        w,
        h,
        r,
        fill,
        (' stroke="%s" stroke-width="%s"' % (stroke, sw)) if stroke else "",
    )


def arrow(x1, y, x2, color):
    return (
        '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s" stroke-width="2"/>'
        '<path d="M%.1f,%.1f l-8,-5 v10 z" fill="%s"/>' % (x1, y, x2 - 7, y, color, x2, y, color)
    )


def pipeline_svg(ev, ref, theme):
    t = THEMES[theme]
    c = ev["claims"]
    steps = {s["step"]: s for s in ref["steps"]}

    def sec(name):
        return "%.1f с" % steps[name]["wall_s"] if steps[name]["wall_s"] >= 0.95 else "<1 с"

    def mem(name):
        v = steps[name]["peak_rss_mb"]
        return "%.1f ГБ" % (v / 1024.0) if v >= 1000 else "%d МБ" % round(v)

    stages = [
        (
            "1",
            "Риды",
            "FASTQ, NovaSeq 2×151",
            ["%s пар" % "{:,}".format(int(c["read_pairs"])).replace(",", " "), "chr20: 10–12 Мб"],
            None,
        ),
        ("2", "fastp", "адаптеры и poly-G", ["%s · %s" % (sec("fastp"), mem("fastp")), "Q30 и дубли в JSON"], "fastp"),
        (
            "3",
            "bwa-mem2",
            "выравнивание + fixmate",
            ["%s · %s" % (sec("bwa_mem2_mem"), mem("bwa_mem2_mem")), "-K 10⁸: не зависит от -t"],
            "bwa_mem2_mem",
        ),
        (
            "4",
            "samtools",
            "sort, markdup, QC",
            ["дубли %s %%" % c["dup_rate_pct"], "глубина %sx" % c["mean_depth"]],
            None,
        ),
        (
            "5",
            "bcftools",
            "mpileup | call | filter",
            ["%s · Ti/Tv %s" % (sec("bcftools_call"), c["ts_tv"]), "-X illumina (indels-cns)"],
            "bcftools_call",
        ),
        ("6", "hap.py", "сверка с GIAB", ["SNV F1 %s" % c["snp_v5_f1"], "INDEL F1 %s" % c["indel_v5_f1"]], None),
    ]
    W, H = 1200, 500
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" '
        'aria-label="Схема пайплайна HG002 mini-WGS">' % (W, H, W, H)
    ]
    out.append(rr(0, 0, W, H, t["bg"], r=16))
    out.append(text(32, 46, "HG002 mini-WGS: от сырых ридов до сверки с эталоном GIAB", 22, "ink", 700, t=t))
    out.append(
        text(
            32,
            72,
            "Каждый шаг — CommandLineTool CWL в контейнере; время и пик памяти измерены внутри шага "
            "(bin/measure.py), эталонный прогон, 4 потока",
            13.5,
            "ink2",
            t=t,
        )
    )
    bw, bh, gap, top = 172, 150, 22, 100
    x0 = (W - (6 * bw + 5 * gap)) / 2.0
    for i, (num, title, sub, lines, _) in enumerate(stages):
        x = x0 + i * (bw + gap)
        last = i == len(stages) - 1
        out.append(
            rr(
                x,
                top,
                bw,
                bh,
                t["chip"] if last else t["panel"],
                t["accent"] if last else t["line"],
                r=14,
                sw=2 if last else 1,
            )
        )
        out.append('<circle cx="%.1f" cy="%.1f" r="13" fill="%s"/>' % (x + 26, top + 28, t["accent"]))
        out.append(text(x + 26, top + 33, num, 13, "bg", 700, "middle", t=t))
        out.append(text(x + 48, top + 33, title, 17, "ink", 700, t=t))
        out.append(text(x + 16, top + 62, sub, 12.5, "ink2", t=t))
        out.append(
            '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="%s"/>'
            % (x + 16, top + 76, x + bw - 16, top + 76, t["line"])
        )
        for j, ln in enumerate(lines):
            out.append(text(x + 16, top + 100 + j * 22, ln, 13.5, "ink", 600 if j == 0 else 400, t=t))
        if not last:
            out.append(arrow(x + bw + 2, top + bh / 2.0, x + bw + gap - 2, t["ink2"]))

    # нижняя полоса: что вокруг пайплайна
    y = top + bh + 34
    out.append(text(32, y, "Обвязка", 15, "ink", 700, t=t))
    chips = [
        "CWL v1.2 · %s инструментов" % c["cwl_tools"],
        "Docker: htslib/samtools/bcftools из исходников",
        "база по digest + snapshot.debian.org",
        "Slurm: sbatch, Toil, job array",
        "GitLab CI + Pages",
        "SQLite: прогоны, точность, варианты",
    ]
    cx, cy = 32, y + 16
    for ch in chips:
        w = 16 + len(ch) * 7.3
        if cx + w > W - 32:
            cx, cy = 32, cy + 40
        out.append(rr(cx, cy, w, 30, t["panel"], t["line"], r=15))
        out.append(text(cx + w / 2.0, cy + 20, ch, 13, "ink", 500, "middle", t=t))
        cx += w + 10

    # лента воспроизводимости
    y2 = cy + 58
    out.append(rr(32, y2, W - 64, 78, t["chip"], t["accent"], r=12))
    out.append(text(52, y2 + 26, "Воспроизводимость и проверки", 14.5, "ink", 700, t=t))
    out.append(
        text(
            52,
            y2 + 48,
            "VCF побайтно одинаковый в %s сравнениях: 4 и 2 потока · повтор · Toil на Slurm · "
            "новый образ · другая машина за прокси · пять сборок bwa-mem2" % c["repro_comparisons"],
            13.5,
            "ink",
            t=t,
        )
    )
    out.append(
        text(
            52,
            y2 + 68,
            "Тесты при сборке образа: htslib %s/%s · samtools %s пройдено, %s ошибок · bcftools %s/%s"
            " · автотесты репозитория: %s"
            % (
                c["htslib_tests_passed"],
                c["htslib_tests_total"],
                c["samtools_tests_passed"],
                c["samtools_tests_failed"],
                c["bcftools_tests_passed"],
                c["bcftools_tests_total"],
                c["unit_tests"],
            ),
            13.5,
            "ink",
            t=t,
        )
    )
    out.append("</svg>")
    return "\n".join(out)


def pipeline_narrow_svg(ev, ref, theme):
    """Вертикальный вариант для экранов до 700 px: шаги друг под другом, текст крупнее."""
    t = THEMES[theme]
    c = ev["claims"]
    steps = {s["step"]: s for s in ref["steps"]}

    def sec(name):
        return "%.1f с" % steps[name]["wall_s"]

    def mem(name):
        v = steps[name]["peak_rss_mb"]
        return "%.1f ГБ" % (v / 1024.0) if v >= 1000 else "%d МБ" % round(v)

    rows = [
        (
            "Риды",
            "NovaSeq 2×151, chr20",
            "%s пар" % "{:,}".format(int(c["read_pairs"])).replace(",", " "),
            "глубина %sx" % c["mean_depth"],
        ),
        ("fastp", "адаптеры и poly-G", sec("fastp"), mem("fastp")),
        ("bwa-mem2", "выравнивание, -K 10⁸", sec("bwa_mem2_mem"), mem("bwa_mem2_mem")),
        ("samtools", "sort, markdup, QC", "дубли %s %%" % c["dup_rate_pct"], "оптич. %s %%" % c["optical_dup_pct"]),
        ("bcftools", "-X illumina", sec("bcftools_call"), "Ti/Tv %s" % c["ts_tv"]),
        ("hap.py", "сверка с GIAB v5.0q", "SNV F1 %s" % c["snp_v5_f1"], "INDEL F1 %s" % c["indel_v5_f1"]),
    ]
    W, card_h, gap, top = 420, 64, 16, 84
    H = top + len(rows) * (card_h + gap) + 104
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" '
        'aria-label="Схема пайплайна HG002 mini-WGS">' % (W, H, W, H)
    ]
    out.append(rr(0, 0, W, H, t["bg"], r=14))
    out.append(text(16, 34, "От сырых ридов до сверки с GIAB", 19, "ink", 700, t=t))
    out.append(text(16, 58, "Время и пик памяти измерены внутри шага", 13, "ink2", t=t))
    for i, (title, sub, right1, right2) in enumerate(rows):
        y = top + i * (card_h + gap)
        last = i == len(rows) - 1
        out.append(
            rr(
                16,
                y,
                W - 32,
                card_h,
                t["chip"] if last else t["panel"],
                t["accent"] if last else t["line"],
                r=12,
                sw=2 if last else 1,
            )
        )
        out.append('<circle cx="38" cy="%.1f" r="12" fill="%s"/>' % (y + card_h / 2.0, t["accent"]))
        out.append(text(38, y + card_h / 2.0 + 4.5, str(i + 1), 12.5, "bg", 700, "middle", t=t))
        out.append(text(60, y + 27, title, 16, "ink", 700, t=t))
        out.append(text(60, y + 47, sub, 12.5, "ink2", t=t))
        out.append(text(W - 30, y + 27, right1, 14, "ink", 600, "end", t=t))
        out.append(text(W - 30, y + 47, right2, 12.5, "ink2", anchor="end", t=t))
        if not last:
            cy = y + card_h + gap / 2.0
            out.append('<path d="M38,%.1f l-5,-4 h10 z" fill="%s"/>' % (cy + 3, t["ink2"]))
    y2 = top + len(rows) * (card_h + gap) + 4
    out.append(rr(16, y2, W - 32, 88, t["chip"], t["accent"], r=12))
    out.append(
        text(
            30,
            y2 + 25,
            "VCF совпал побайтно: %s из %s сравнений" % (c["repro_comparisons"], c["repro_comparisons"]),
            13.5,
            "ink",
            700,
            t=t,
        )
    )
    out.append(
        text(
            30,
            y2 + 48,
            "Тесты сборки: htslib %s/%s, bcftools %s/%s"
            % (
                c["htslib_tests_passed"],
                c["htslib_tests_total"],
                c["bcftools_tests_passed"],
                c["bcftools_tests_total"],
            ),
            12.5,
            "ink",
            t=t,
        )
    )
    out.append(
        text(
            30,
            y2 + 70,
            "samtools: %s пройдено, %s ошибок · автотестов %s"
            % (c["samtools_tests_passed"], c["samtools_tests_failed"], c["unit_tests"]),
            12.5,
            "ink",
            t=t,
        )
    )
    out.append("</svg>")
    return "\n".join(out)


STRATA = [
    ("*", "весь регион"),
    ("not_in_all_difficult", "вне сложных участков"),
    ("all_difficult", "все сложные участки"),
    ("homopolymers_ge7", "гомополимеры ≥ 7 п.н."),
    ("tandem_repeats", "тандемные повторы"),
    ("gc_lt25_or_gt65", "GC < 25 % или > 65 %"),
]


def accuracy_svg(ref, theme):
    t = THEMES[theme]
    b = ref["benchmark"]
    truths = [
        ("giab_v5.0q", "GIAB v5.0q (Q100, текущий)", t["accent"]),
        ("giab_v4.2.1", "GIAB v4.2.1 (классический)", t["accent2"]),
    ]
    W, H = 1200, 486
    lo, hi = 0.75, 1.0
    left, panel_w, top, row_h = 230, 420, 156, 42
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" '
        'aria-label="Точность по типам участков генома">' % (W, H, W, H)
    ]
    out.append(rr(0, 0, W, H, t["bg"], r=16))
    out.append(text(32, 46, "Где ошибается вызов: F1 с 95 % доверительным интервалом", 22, "ink", 700, t=t))
    out.append(
        text(
            32,
            72,
            "PASS-варианты, стратификации GIAB v3.6. Вне сложных участков почти без ошибок; "
            "основная часть ошибок в тандемных повторах и гомополимерах.",
            13.5,
            "ink2",
            t=t,
        )
    )
    lx = 32
    for _, label, color in truths:
        out.append('<circle cx="%.1f" cy="96" r="6" fill="%s"/>' % (lx + 6, color))
        out.append(text(lx + 18, 101, label, 13, "ink", t=t))
        lx += 26 + len(label) * 7.4
    for pi, vtype in enumerate(("SNP", "INDEL")):
        px = left + pi * (panel_w + 80)
        sx = lambda v, px=px: px + (v - lo) / (hi - lo) * panel_w  # noqa: E731
        out.append(text(px, top - 4, "SNV" if vtype == "SNP" else "Инделы", 15, "ink", 700, t=t))
        yb = top + 14 + row_h * len(STRATA)
        for tick in (0.75, 0.80, 0.85, 0.90, 0.95, 1.00):
            out.append(
                '<line x1="%.1f" x2="%.1f" y1="%d" y2="%d" stroke="%s"/>'
                % (sx(tick), sx(tick), top + 10, yb, t["line"])
            )
            out.append(text(sx(tick), yb + 18, "%.2f" % tick, 12, "ink2", anchor="middle", t=t))
        for ri, (key, label) in enumerate(STRATA):
            yc = top + 14 + ri * row_h + row_h / 2.0
            if pi == 0:
                out.append(text(32, yc + 5, label, 13.5, "ink", t=t))
            for ti, (truth, _, color) in enumerate(truths):
                if key == "*":
                    r = next(x for x in b[truth]["summary"] if x["type"] == vtype and x["filter"] == "PASS")
                else:
                    r = next((x for x in b[truth]["strata"] if x["subset"] == key and x["type"] == vtype), None)
                if not r or r["f1"] is None:
                    continue
                y = yc + (ti - 0.5) * 11
                clo, chi = r["f1_ci"]
                out.append(
                    '<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="2.5" '
                    'stroke-linecap="round"/>' % (sx(max(lo, clo)), sx(min(hi, chi)), y, y, color)
                )
                out.append(
                    '<circle cx="%.1f" cy="%.1f" r="5" fill="%s" stroke="%s" stroke-width="2"/>'
                    % (sx(max(lo, r["f1"])), y, color, t["bg"])
                )
                if ti == 0:
                    out.append(text(px + panel_w + 8, y + 4, "%.3f" % r["f1"], 11.5, "ink2", t=t))
    out.append(
        text(
            32,
            H - 18,
            "Точки ниже 0.75 прижаты к краю оси. Данные: docs/results/reference/HG002.report.json",
            11.5,
            "ink2",
            t=t,
        )
    )
    out.append("</svg>")
    return "\n".join(out)


def accuracy_narrow_svg(ref, theme):
    """Вертикальный вариант графика точности: панели SNV и инделов одна под другой."""
    t = THEMES[theme]
    b = ref["benchmark"]
    truths = [("giab_v5.0q", "GIAB v5.0q (текущий)", t["accent"]), ("giab_v4.2.1", "GIAB v4.2.1", t["accent2"])]
    W, lo, hi = 420, 0.75, 1.0
    left, plot_w, row_h = 168, 224, 34
    panel_h = 30 + row_h * len(STRATA) + 30
    top = 96
    H = top + 2 * panel_h + 36
    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" '
        'aria-label="Точность по типам участков генома">' % (W, H, W, H)
    ]
    out.append(rr(0, 0, W, H, t["bg"], r=14))
    out.append(text(16, 34, "F1 с 95 % ДИ по участкам генома", 18, "ink", 700, t=t))
    lx = 16
    for _, label, color in truths:
        out.append('<circle cx="%.1f" cy="62" r="6" fill="%s"/>' % (lx + 6, color))
        out.append(text(lx + 17, 66.5, label, 12.5, "ink", t=t))
        lx += 30 + len(label) * 7.0
    sx = lambda v: left + (v - lo) / (hi - lo) * plot_w  # noqa: E731
    for pi, vtype in enumerate(("SNP", "INDEL")):
        py = top + pi * panel_h
        out.append(text(16, py + 16, "SNV" if vtype == "SNP" else "Инделы", 15, "ink", 700, t=t))
        y0, yb = py + 26, py + 26 + row_h * len(STRATA)
        for tick in (0.75, 0.85, 0.95):
            out.append(
                '<line x1="%.1f" x2="%.1f" y1="%d" y2="%d" stroke="%s"/>' % (sx(tick), sx(tick), y0, yb, t["line"])
            )
            out.append(text(sx(tick), yb + 16, "%.2f" % tick, 11.5, "ink2", anchor="middle", t=t))
        out.append('<line x1="%.1f" x2="%.1f" y1="%d" y2="%d" stroke="%s"/>' % (sx(1.0), sx(1.0), y0, yb, t["line"]))
        out.append(text(sx(1.0), yb + 16, "1.00", 11.5, "ink2", anchor="end", t=t))
        for ri, (key, label) in enumerate(STRATA):
            yc = y0 + ri * row_h + row_h / 2.0
            out.append(text(16, yc + 4.5, label, 12.5, "ink", t=t))
            for ti, (truth, _, color) in enumerate(truths):
                if key == "*":
                    r = next(x for x in b[truth]["summary"] if x["type"] == vtype and x["filter"] == "PASS")
                else:
                    r = next((x for x in b[truth]["strata"] if x["subset"] == key and x["type"] == vtype), None)
                if not r or r["f1"] is None:
                    continue
                y = yc + (ti - 0.5) * 9
                clo, chi = r["f1_ci"]
                out.append(
                    '<line x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f" stroke="%s" stroke-width="2.5" '
                    'stroke-linecap="round"/>' % (sx(max(lo, clo)), sx(min(hi, chi)), y, y, color)
                )
                out.append(
                    '<circle cx="%.1f" cy="%.1f" r="4.5" fill="%s" stroke="%s" stroke-width="2"/>'
                    % (sx(max(lo, r["f1"])), y, color, t["bg"])
                )
    out.append(text(16, H - 14, "Точки ниже 0.75 прижаты к краю оси", 11.5, "ink2", t=t))
    out.append("</svg>")
    return "\n".join(out)


def main():
    with open(os.path.join(ROOT, "evidence.json"), encoding="utf-8") as fh:
        ev = json.load(fh)
    with open(os.path.join(ROOT, "docs", "results", "reference", "HG002.report.json"), encoding="utf-8") as fh:
        ref = json.load(fh)
    os.makedirs(OUT, exist_ok=True)
    for theme in THEMES:
        for name, svg in (
            ("pipeline", pipeline_svg(ev, ref, theme)),
            ("accuracy", accuracy_svg(ref, theme)),
            ("pipeline-narrow", pipeline_narrow_svg(ev, ref, theme)),
            ("accuracy-narrow", accuracy_narrow_svg(ref, theme)),
        ):
            with open(os.path.join(OUT, "%s-%s.svg" % (name, theme)), "w", encoding="utf-8") as fh:
                fh.write(svg + "\n")
    print("written: docs/assets/{pipeline,accuracy}[-narrow]-{light,dark}.svg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
