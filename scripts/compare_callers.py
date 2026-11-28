#!/usr/bin/env python3
"""Сравнение вызывателей на одних и тех же выравниваниях: GA4GH, страты, Макнемар, ресурсы.

    python3 scripts/compare_callers.py bcftools=results/run strelka2=results/callers/strelka2 \\
        [--base bcftools] [--json compare.json] [--md compare.md] [--export docs/results/callers]

Каждый каталог — выход mini-wgs.cwl или call-<caller>.cwl: <truth>.summary.csv,
<truth>.extended.csv, <truth>.vcf.gz (размеченный VCF hap.py) и *.metrics.json шагов
(или <sample>.step_metrics.tsv основного прогона).

Что считается:
  * recall, precision, F1 по PASS с 95 % интервалами (как в отчёте прогона);
  * F1 по стратам GIAB (тандемные повторы, гомополимеры, все сложные участки, остальное);
  * парный точный тест Макнемара по истинным вариантам: b — нашёл только --base,
    c — нашёл только другой вызыватель, p = двусторонний биномиальный тест b из b + c.
    Вызыватели видят одни и те же истинные варианты, поэтому парный тест строже, чем
    «интервалы F1 не пересекаются». Вариант засчитан, если в строке hap.py у эталона
    BD=TP и FILTER строки PASS; ключ — позиция и аллели эталона из GT, обрезанные
    по общему суффиксу и префиксу;
  * время, CPU (user + sys) и пик памяти шагов вызова, как в отчёте прогона.

--export DIR копирует первоисточники (summary/extended CSV, step_metrics.tsv) в
DIR/<caller>/, чтобы их можно было закоммитить без больших VCF.
"""

import argparse
import glob
import gzip
import json
import math
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_report import benchmark_row, read_csv  # noqa: E402

TRUTHS = ("giab_v5.0q", "giab_v4.2.1")
TYPES = ("SNP", "INDEL")
STRATA = (
    ("not_in_all_difficult", "вне сложных участков"),
    ("all_difficult", "все сложные участки"),
    ("tandem_repeats", "тандемные повторы"),
    ("homopolymers_ge7", "гомополимеры ≥ 7"),
    ("low_mappability", "низкая картируемость"),
    ("segdups", "сегментные дупликации"),
)
# Steps that make up "calling" for each caller (alignment is shared).
CALL_STEPS = {
    "bcftools": ("bcftools_call", "bcftools_filter"),
    "strelka2": ("strelka2_germline", "strelka2_vcf", "strelka2_gvcf"),
    "deepvariant": ("deepvariant", "deepvariant_vcf", "deepvariant_gvcf"),
}
STEP_FIELDS = ("wall_s", "user_s", "sys_s", "peak_rss_mb", "threads")


# ----------------------------------------------------------------- статистика


def mcnemar_exact(b, c):
    """Двусторонний точный тест Макнемара: биномиальный тест b из b + c при p = 1/2."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2.0**n
    return min(1.0, 2 * tail)


def trim_alleles(pos, ref, alts):
    """Обрезать общий суффикс, затем общий префикс (оставляя по основанию)."""
    alleles = [ref] + list(alts)
    while all(len(a) > 1 for a in alleles) and len({a[-1] for a in alleles}) == 1:
        alleles = [a[:-1] for a in alleles]
    while all(len(a) > 1 for a in alleles) and len({a[0] for a in alleles}) == 1:
        alleles = [a[1:] for a in alleles]
        pos += 1
    return pos, alleles[0], tuple(alleles[1:])


def truth_key(chrom, pos, ref, alts, gt):
    """Ключ истинного варианта: позиция и аллели из GT эталона, без REF-аллеля."""
    idx = sorted({int(x) for x in gt.replace("|", "/").split("/") if x not in (".", "0")})
    called = [alts[i - 1] for i in idx if 0 < i <= len(alts)]
    p, r, a = trim_alleles(int(pos), ref.upper(), [x.upper() for x in called])
    return "%s:%d:%s:%s" % (chrom, p, r, ",".join(a))


def happy_truth_calls(vcf_path):
    """{тип: {ключ: True/False}} — найден ли PASS-вызовом каждый истинный вариант."""
    out = {t: {} for t in TYPES}
    with gzip.open(vcf_path, "rt") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            f = line.rstrip("\n").split("\t")
            keys = f[8].split(":")
            truth = dict(zip(keys, f[9].split(":")))
            bd, vt = truth.get("BD"), truth.get("BVT")
            if bd not in ("TP", "FN") or vt not in out:
                continue
            key = truth_key(f[0], f[1], f[3], f[4].split(","), truth.get("GT", "."))
            found = bd == "TP" and f[6] in ("PASS", ".")
            out[vt][key] = out[vt].get(key, False) or found
    return out


# ----------------------------------------------------------------- чтение каталога


def read_steps(run_dir):
    rows = []
    for path in sorted(glob.glob(os.path.join(run_dir, "*.metrics.json"))):
        with open(path, encoding="utf-8") as fh:
            m = json.load(fh)
        rows.append({k: m.get(k) for k in ("step",) + STEP_FIELDS})
    if rows:
        return rows
    for path in sorted(glob.glob(os.path.join(run_dir, "*step_metrics.tsv"))):
        with open(path, encoding="utf-8") as fh:
            header = fh.readline().rstrip("\n").split("\t")
            for line in fh:
                d = dict(zip(header, line.rstrip("\n").split("\t")))
                rows.append({"step": d["step"], **{k: float(d[k]) for k in STEP_FIELDS}})
    return rows


def resources(name, steps):
    wanted = CALL_STEPS.get(name)
    sel = [s for s in steps if wanted is None or s["step"] in wanted]
    if not sel:
        return None
    return {
        "steps": sorted(s["step"] for s in sel),
        "wall_s": round(sum(s["wall_s"] for s in sel), 1),
        "cpu_s": round(sum(s["user_s"] + s["sys_s"] for s in sel), 1),
        "peak_rss_mb": round(max(s["peak_rss_mb"] for s in sel), 1),
        "threads": max(int(s["threads"] or 1) for s in sel),
    }


def read_caller(run_dir):
    out = {"truths": {}, "vcfs": {}}
    for truth in TRUTHS:
        summ = os.path.join(run_dir, truth + ".summary.csv")
        if not os.path.exists(summ):
            continue
        rows = [benchmark_row(r) for r in read_csv(summ) if r["Filter"] == "PASS"]
        entry = {r["type"]: r for r in rows if r["type"] in TYPES}
        ext = os.path.join(run_dir, truth + ".extended.csv")
        strata = {}
        if os.path.exists(ext):
            for r in read_csv(ext):
                if r["Filter"] == "PASS" and r["Subtype"] == "*" and r["Type"] in TYPES:
                    strata.setdefault(r["Subset"], {})[r["Type"]] = benchmark_row(r)
        entry["strata"] = strata
        out["truths"][truth] = entry
        vcf = os.path.join(run_dir, truth + ".vcf.gz")
        if os.path.exists(vcf):
            out["vcfs"][truth] = vcf
    out["steps"] = read_steps(run_dir)
    return out


def slim(r):
    keys = ("truth_total", "tp", "fn", "fp", "recall", "recall_ci", "precision", "precision_ci", "f1", "f1_ci")
    return {k: r.get(k) for k in keys}


# ----------------------------------------------------------------- сравнение


def compare(callers, base):
    """callers: {name: run_dir} (порядок сохраняется)."""
    data = {name: read_caller(d) for name, d in callers.items()}
    res = {"base": base, "callers": list(callers), "benchmark": {}, "strata": {}, "mcnemar": {}, "resources": {}}
    for truth in TRUTHS:
        if not all(truth in data[n]["truths"] for n in callers):
            continue
        res["benchmark"][truth] = {n: {t: slim(data[n]["truths"][truth][t]) for t in TYPES} for n in callers}
        res["strata"][truth] = {
            n: {
                s: {t: slim(data[n]["truths"][truth]["strata"][s][t]) for t in TYPES}
                for s, _ in STRATA
                if s in data[n]["truths"][truth]["strata"]
            }
            for n in callers
        }
        if not all(truth in data[n]["vcfs"] for n in callers):
            continue
        calls = {n: happy_truth_calls(data[n]["vcfs"][truth]) for n in callers}
        res["mcnemar"][truth] = {}
        for other in callers:
            if other == base:
                continue
            entry = {}
            for t in TYPES:
                a, b = calls[base][t], calls[other][t]
                common = set(a) & set(b)
                only_base = sum(1 for k in common if a[k] and not b[k])
                only_other = sum(1 for k in common if b[k] and not a[k])
                entry[t] = {
                    "pairs": len(common),
                    "unpaired": len(set(a) ^ set(b)),
                    "found_by_base": sum(1 for k in common if a[k]),
                    "found_by_other": sum(1 for k in common if b[k]),
                    "only_base": only_base,
                    "only_other": only_other,
                    "p": mcnemar_exact(only_base, only_other),
                }
            res["mcnemar"][truth][other] = entry
    for n in callers:
        r = resources(n, data[n]["steps"])
        if r:
            res["resources"][n] = r
    return res


# ----------------------------------------------------------------- вывод


def f4(x):
    return "—" if x is None else "%.4f" % x


def ci(c):
    return "—" if not c or c[0] is None else "%.3f–%.3f" % tuple(c)


def pval(p):
    return "%.2g" % p if p < 0.001 else "%.3f" % p


def render_md(res):
    lines = ["# Сравнение вызывателей на одних выравниваниях", ""]
    lines.append(
        "PASS-вызовы, внутри доверенных участков эталона, hap.py (GA4GH). Интервалы 95 %%: "
        "Уилсона для recall и precision, Монте-Карло для F1. Порядок вызывателей: %s." % ", ".join(res["callers"])
    )
    for truth, by_caller in res["benchmark"].items():
        lines += ["", "## %s" % truth, ""]
        lines.append("| Вызыватель | Тип | TP | FN | FP | Recall [95 % ДИ] | Precision [95 % ДИ] | F1 [95 % ДИ] |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for t in TYPES:
            for n, rows in by_caller.items():
                r = rows[t]
                lines.append(
                    "| %s | %s | %d | %d | %d | %s [%s] | %s [%s] | **%s** [%s] |"
                    % (
                        n,
                        t,
                        r["tp"],
                        r["fn"],
                        r["fp"],
                        f4(r["recall"]),
                        ci(r["recall_ci"]),
                        f4(r["precision"]),
                        ci(r["precision_ci"]),
                        f4(r["f1"]),
                        ci(r["f1_ci"]),
                    )
                )
        mc = res["mcnemar"].get(truth)
        if mc:
            lines += ["", "Парный тест Макнемара по истинным вариантам (база — %s):" % res["base"], ""]
            lines.append("| Сравнение | Тип | Пар | Нашёл только %s | Нашёл только другой | p |" % res["base"])
            lines.append("|---|---|---|---|---|---|")
            for other, entry in mc.items():
                for t in TYPES:
                    e = entry[t]
                    lines.append(
                        "| %s → %s | %s | %d | %d | %d | %s |"
                        % (res["base"], other, t, e["pairs"], e["only_base"], e["only_other"], pval(e["p"]))
                    )
        st = res["strata"].get(truth)
        if st:
            lines += ["", "F1 по стратам GIAB:", ""]
            lines.append("| Страта | Тип | " + " | ".join(res["callers"]) + " |")
            lines.append("|---|---|" + "---|" * len(res["callers"]))
            for s, label in STRATA:
                for t in TYPES:
                    vals = []
                    for n in res["callers"]:
                        r = st[n].get(s, {}).get(t)
                        vals.append("—" if not r or r["f1"] is None else "%.3f (%d)" % (r["f1"], r["truth_total"]))
                    lines.append("| %s | %s | %s |" % (label, t, " | ".join(vals)))
            lines.append("")
            lines.append("В скобках — число истинных вариантов в страте.")
    if res["resources"]:
        lines += ["", "## Ресурсы шагов вызова", ""]
        lines.append("| Вызыватель | Шаги | Потоков | Время, с | CPU, с | Пик памяти, МБ |")
        lines.append("|---|---|---|---|---|---|")
        for n, r in res["resources"].items():
            lines.append(
                "| %s | %s | %d | %.1f | %.1f | %.0f |"
                % (n, ", ".join(r["steps"]), r["threads"], r["wall_s"], r["cpu_s"], r["peak_rss_mb"])
            )
    return "\n".join(lines) + "\n"


def export(callers, out_dir):
    for name, run_dir in callers.items():
        dst = os.path.join(out_dir, name)
        os.makedirs(dst, exist_ok=True)
        for truth in TRUTHS:
            for kind in ("summary", "extended"):
                src = os.path.join(run_dir, "%s.%s.csv" % (truth, kind))
                if os.path.exists(src):
                    shutil.copyfile(src, os.path.join(dst, os.path.basename(src)))
        steps = read_steps(run_dir)
        with open(os.path.join(dst, "step_metrics.tsv"), "w", encoding="utf-8") as fh:
            fh.write("step\t" + "\t".join(STEP_FIELDS) + "\n")
            for s in steps:
                fh.write(s["step"] + "\t" + "\t".join(str(s[k]) for k in STEP_FIELDS) + "\n")


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("runs", nargs="+", help="name=DIR, in display order")
    p.add_argument("--base", help="caller the others are compared with (default: the first)")
    p.add_argument("--json", help="write the comparison as JSON")
    p.add_argument("--md", help="write the comparison as Markdown")
    p.add_argument("--export", help="copy summary/extended CSV and step metrics into DIR/<name>/")
    return p.parse_args(argv)


def main(argv=None):
    a = parse_args(argv)
    callers = {}
    for item in a.runs:
        name, sep, d = item.partition("=")
        if not sep or not os.path.isdir(d):
            sys.stderr.write("expected name=DIR with an existing directory: %s\n" % item)
            return 2
        callers[name] = d
    base = a.base or next(iter(callers))
    if base not in callers:
        sys.stderr.write("--base %s is not among the runs\n" % base)
        return 2
    res = compare(callers, base)
    md = render_md(res)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=2, sort_keys=True, ensure_ascii=False)
            fh.write("\n")
    if a.md:
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write(md)
    if a.export:
        export(callers, a.export)
    if not (a.json or a.md):
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
