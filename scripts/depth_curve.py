#!/usr/bin/env python3
"""Точность от глубины: GA4GH и метрика патента RU 2846268 на прореженных данных.

    python3 scripts/depth_curve.py results/depth --truth-dir data/truth --ref data/ref/ref.fa \\
        --json docs/results/depth/curve.json --md docs/results/depth/curve.md

Каталог серии строит scripts/depth_series.sh: f<доля>_s<зерно>/{run,strelka2,deepvariant}.
Для каждой точки и вызывателя считаются recall, precision и F1 hap.py по PASS с 95 %
интервалами (как в отчёте прогона) и F по формуле патента как в патенте (literal), а
рядом — какая доля эталонных вариантов вообще вошла в знаменатель F. Фильтры патента
(GQ > 10, sum(AD) > 10) на малой глубине убирают из расчёта всё больше вызовов, и F
считается по всё меньшей части эталона.

Точки с одной долей и разными зёрнами — повторы: их разброс показывает, насколько число
меняется только от того, какие риды попали в выборку.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare_callers import read_caller, slim  # noqa: E402
from concordance import evaluate  # noqa: E402

TRUTHS = ("giab_v5.0q", "giab_v4.2.1")
TYPES = ("SNP", "INDEL")
CALLERS = (
    ("bcftools", "run", "HG002.vcf.gz"),
    ("strelka2", "strelka2", "HG002.strelka2.vcf.gz"),
    ("deepvariant", "deepvariant", "HG002.deepvariant.vcf.gz"),
)
POINT = re.compile(r"^f([0-9.]+)_s(\d+)$")
THRESHOLD = 0.999  # порог пригодности протокола в патенте


def read_point(path, truth_dir, ref):
    name = os.path.basename(path)
    m = POINT.match(name)
    with open(os.path.join(path, "run", "HG002.report.json"), encoding="utf-8") as fh:
        rep = json.load(fh)
    point = {
        "label": name,
        "fraction": float(m.group(1)),
        "seed": int(m.group(2)),
        "pairs": rep["reads"]["pairs_before"],
        "mean_depth": rep["alignment"]["mean_depth"],
        "callers": {},
    }
    vcfs = {}
    for caller, sub, vcf in CALLERS:
        d = os.path.join(path, sub)
        if not os.path.exists(os.path.join(d, "giab_v5.0q.summary.csv")):
            continue
        data = read_caller(d)
        point["callers"][caller] = {
            truth: {t: slim(data["truths"][truth][t]) for t in TYPES} for truth in TRUTHS if truth in data["truths"]
        }
        vcfs[caller] = os.path.join(d, vcf)
    for truth, per_caller in evaluate(vcfs, truth_dir, ref).items():
        for caller, e in per_caller.items():
            lit = e["literal"]
            point["callers"][caller][truth]["patent"] = {
                "f": lit["f"],
                "numerator": lit["numerator"],
                "denominator": lit["denominator"],
                "truth_in_denominator_share": lit["truth_in_denominator_share"],
                "pass": lit["f"] is not None and lit["f"] > THRESHOLD,
            }
    return point


def replicate_spread(points):
    """Для долей с несколькими зёрнами: размах F1 и F по зёрнам (max − min)."""
    out = {}
    by_frac = {}
    for p in points:
        by_frac.setdefault(p["fraction"], []).append(p)
    for frac, ps in sorted(by_frac.items()):
        if len(ps) < 2:
            continue
        entry = {"seeds": sorted(p["seed"] for p in ps), "depths": sorted(p["mean_depth"] for p in ps)}
        for caller in ps[0]["callers"]:
            if not all(caller in p["callers"] for p in ps):
                continue
            for truth in TRUTHS:
                for vtype in TYPES:
                    f1 = [p["callers"][caller][truth][vtype]["f1"] for p in ps]
                    entry["%s %s %s F1" % (caller, truth, vtype)] = [min(f1), max(f1)]
                pf = [p["callers"][caller][truth]["patent"]["f"] for p in ps]
                entry["%s %s F" % (caller, truth)] = [min(pf), max(pf)]
        out["%.3g" % frac] = entry
    return out


def f4(x):
    return "–" if x is None else "%.4f" % x


def pct(x, d=2):
    return "–" if x is None else ("%." + str(d) + "f") % (100 * x)


def render_md(res):
    pts = [p for p in res["points"] if p["seed"] == 1]
    callers = [c for c, _, _ in CALLERS if all(c in p["callers"] for p in pts)]
    md = ["# Точность от глубины\n"]
    md.append(
        "HG002, chr20:10–12 Мб, прореживание пар ридов (`samtools view -s`), зерно 1. "
        "F1 — hap.py, PASS, с 95 % интервалом; F — формула патента RU 2846268 как в патенте "
        "(GQ > 10, sum(AD) > 10, PASS, точное совпадение CHR/POS/REF/ALT); «в знаменателе» — доля "
        "эталонных вариантов, которые вообще вошли в знаменатель F.\n"
    )
    for truth in TRUTHS:
        md.append("## %s\n" % truth)
        head = ["глубина", "пар"]
        for c in callers:
            head += ["%s SNV F1" % c, "%s инделы F1" % c, "%s F, %%" % c, "%s в знаменателе, %%" % c]
        rows = []
        for p in sorted(pts, key=lambda p: -p["mean_depth"]):
            row = ["%.1fx" % p["mean_depth"], str(p["pairs"])]
            for c in callers:
                e = p["callers"][c][truth]
                row += [
                    "%s [%s–%s]" % (f4(e["SNP"]["f1"]), "%.3f" % e["SNP"]["f1_ci"][0], "%.3f" % e["SNP"]["f1_ci"][1]),
                    "%s [%s–%s]"
                    % (f4(e["INDEL"]["f1"]), "%.3f" % e["INDEL"]["f1_ci"][0], "%.3f" % e["INDEL"]["f1_ci"][1]),
                    pct(e["patent"]["f"], 3) + (" ✓" if e["patent"]["pass"] else ""),
                    pct(e["patent"]["truth_in_denominator_share"], 1),
                ]
            rows.append(row)
        md.append("| " + " | ".join(head) + " |")
        md.append("|" + "---|" * len(head))
        md += ["| " + " | ".join(r) + " |" for r in rows]
        md.append("")
    md.append("✓ — F выше порога 99,9 %.\n")
    if res["replicates"]:
        md.append("## Повторы: разброс между зёрнами\n")
        md.append("| доля | зёрна | глубина | показатель | min | max |")
        md.append("|---|---|---|---|---|---|")
        for frac, e in res["replicates"].items():
            depth = "%.1f–%.1fx" % (e["depths"][0], e["depths"][-1])
            for k, v in e.items():
                if k in ("seeds", "depths"):
                    continue
                is_f = k.endswith(" F")
                fmt = (lambda x: pct(x, 3)) if is_f else f4
                md.append(
                    "| %s | %s | %s | %s | %s | %s |"
                    % (frac, ",".join(map(str, e["seeds"])), depth, k + (", %" if is_f else ""), fmt(v[0]), fmt(v[1]))
                )
        md.append("")
    return "\n".join(md)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("series", help="каталог scripts/depth_series.sh")
    p.add_argument("--truth-dir", default="data/truth")
    p.add_argument("--ref", default="data/ref/ref.fa")
    p.add_argument("--json")
    p.add_argument("--md")
    a = p.parse_args(argv)
    dirs = sorted(
        os.path.join(a.series, d)
        for d in os.listdir(a.series)
        if POINT.match(d) and os.path.exists(os.path.join(a.series, d, "run", "HG002.report.json"))
    )
    points = [read_point(d, a.truth_dir, a.ref) for d in dirs]
    points.sort(key=lambda p: (-p["fraction"], p["seed"]))
    res = {"threshold": THRESHOLD, "points": points, "replicates": replicate_spread(points)}
    md = render_md(res)
    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=2, sort_keys=True, ensure_ascii=False)
            fh.write("\n")
    if a.md:
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write(md)
    if not (a.json or a.md):
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
