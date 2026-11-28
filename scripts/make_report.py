#!/usr/bin/env python3
"""Отчёт по одному прогону: report.md, report.html, report.json, step_metrics.tsv.

Читает только файлы, которые создал workflow (только stdlib, работает в образе tools):
  * метрики шагов      <step>.metrics.json от bin/measure.py
  * риды               JSON fastp
  * выравнивание       JSON samtools markdup, flagstat, stats, coverage
  * варианты           bcftools stats
  * сверка с эталоном  hap.py summary.csv / extended.csv / размеченный VCF на каждый эталон

Статистика (обоснование в docs/METHODOLOGY.md):
  * 95% интервал Уилсона для recall = TP/(TP+FN) и precision = TP/(TP+FP);
  * интервал F1 методом Монте-Карло по апостериорным Beta (априорное Джеффриса),
    зерно фиксировано, поэтому отчёт воспроизводим;
  * распределение глубины против Пуассона и отрицательного биномиального с тем же средним;
  * точный тест Фишера: обогащены ли ложноположительные SNV заменой C>A (G>T),
    сигнатурой окислительного повреждения 8-oxoG, по сравнению с истинными.
"""

import argparse
import csv
import gzip
import json
import math
import os
import random
import sys
import time

Z95 = 1.959964
GENOME_BP = 3.1e9
STEP_ORDER = [
    "fastp",
    "bwa_mem2_index",
    "bwa_mem2_mem",
    "samtools_sort",
    "samtools_markdup",
    "samtools_qc",
    "bcftools_call",
    "bcftools_filter",
    "bcftools_stats",
]

# ----------------------------------------------------------------- статистика


def wilson(k, n, z=Z95):
    """Интервал Уилсона для доли k/n."""
    if n == 0:
        return (None, None)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def f1_interval(tp_truth, fn, tp_query, fp, draws=20000, seed=20261125):
    """95% интервал F1 по независимым апостериорным Джеффриса для recall и precision.

    Recall и precision делят одни и те же TP, поэтому независимость слегка
    расширяет интервал: оценка консервативная."""
    if tp_truth + fn == 0 or tp_query + fp == 0:
        return (None, None)
    rng = random.Random(seed)
    vals = []
    for _ in range(draws):
        r = rng.betavariate(tp_truth + 0.5, fn + 0.5)
        p = rng.betavariate(tp_query + 0.5, fp + 0.5)
        vals.append(2 * p * r / (p + r) if p + r > 0 else 0.0)
    vals.sort()
    return (vals[int(0.025 * draws)], vals[int(0.975 * draws) - 1])


def poisson_cdf_below(k, lam):
    """P(X < k), X ~ Poisson(lam)."""
    term, total = math.exp(-lam), 0.0
    for i in range(k):
        if i > 0:
            term *= lam / i
        total += term
    return total


def negbin_pmf(i, mean, var):
    r = mean * mean / (var - mean)
    p = r / (r + mean)
    return math.exp(math.lgamma(i + r) - math.lgamma(r) - math.lgamma(i + 1) + r * math.log(p) + i * math.log(1 - p))


def negbin_cdf_below(k, mean, var):
    """P(X < k) для отрицательного биномиального с данными средним и дисперсией (var > mean)."""
    if var <= mean:
        return poisson_cdf_below(k, mean)
    return sum(negbin_pmf(i, mean, var) for i in range(k))


def fisher_exact_two_sided(a, b, c, d):
    """Двусторонний точный тест Фишера для таблицы 2x2 [[a, b], [c, d]]."""
    n1, n2, m1 = a + b, c + d, a + c
    n = n1 + n2

    def log_hyper(x):
        return (
            math.lgamma(n1 + 1)
            - math.lgamma(x + 1)
            - math.lgamma(n1 - x + 1)
            + math.lgamma(n2 + 1)
            - math.lgamma(m1 - x + 1)
            - math.lgamma(n2 - m1 + x + 1)
            - math.lgamma(n + 1)
            + math.lgamma(m1 + 1)
            + math.lgamma(n - m1 + 1)
        )

    lo, hi = max(0, m1 - n2), min(m1, n1)
    p_obs = log_hyper(a)
    total = sum(math.exp(log_hyper(x)) for x in range(lo, hi + 1) if log_hyper(x) <= p_obs + 1e-9)
    return min(1.0, total)


COMPLEMENT = {"A": "T", "C": "G", "G": "C", "T": "A"}
SNV_CLASSES = ["C>A", "C>G", "C>T", "T>A", "T>C", "T>G"]


def snv_class(ref, alt):
    """Замена на пиримидиновой цепи (6 классов, как в сигнатурах мутаций)."""
    ref, alt = ref.upper(), alt.upper()
    if ref in ("G", "A"):
        ref, alt = COMPLEMENT[ref], COMPLEMENT[alt]
    return "%s>%s" % (ref, alt)


# ----------------------------------------------------------------- чтение файлов


def load_json(path):
    if not path:
        return None
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as fh:
        return json.load(fh)


def parse_samtools_stats(path):
    sn, cov = {}, []
    if not path:
        return sn, cov
    with open(path) as fh:
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if f[0] == "SN":
                try:
                    sn[f[1].rstrip(":")] = float(f[2])
                except ValueError:
                    sn[f[1].rstrip(":")] = f[2]
            elif f[0] == "COV":
                cov.append((int(f[2]), int(f[3])))
    return sn, cov


def parse_bcftools_stats(path):
    out = {"SN": {}, "TSTV": None, "ST": {}, "PSC": None}
    if not path:
        return out
    with open(path) as fh:
        for line in fh:
            f = line.rstrip("\n").split("\t")
            if f[0] == "SN":
                out["SN"][f[2].rstrip(":")] = int(f[3])
            elif f[0] == "TSTV":
                out["TSTV"] = {"ts": int(f[2]), "tv": int(f[3]), "ts_tv": float(f[4])}
            elif f[0] == "ST":
                out["ST"][f[2]] = int(f[3])
            elif f[0] == "PSC":
                out["PSC"] = {
                    "ref_hom": int(f[3]),
                    "nonref_hom": int(f[4]),
                    "het": int(f[5]),
                    "indels": int(f[8]),
                    "mean_depth": float(f[9]),
                }
    return out


def parse_coverage_tsv(path):
    if not path:
        return []
    with open(path) as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    return [{k.lstrip("#"): v for k, v in r.items()} for r in rows]


def read_csv(path):
    with open(path) as fh:
        return list(csv.DictReader(fh))


def _num(x, cast=float):
    try:
        return cast(x)
    except (TypeError, ValueError):
        return None


def benchmark_row(row):
    """Строка hap.py summary/extended в едином виде, с интервалами."""
    tp_t = _num(row.get("TRUTH.TP"), int) or 0
    fn = _num(row.get("TRUTH.FN"), int) or 0
    tp_q = _num(row.get("QUERY.TP"), int)
    fp = _num(row.get("QUERY.FP"), int) or 0
    if tp_q is None:  # в summary.csv нет QUERY.TP: TOTAL - FP - UNK
        tp_q = (_num(row.get("QUERY.TOTAL"), int) or 0) - fp - (_num(row.get("QUERY.UNK"), int) or 0)
    return {
        "type": row.get("Type"),
        "filter": row.get("Filter"),
        "subset": row.get("Subset", "*"),
        "truth_total": tp_t + fn,
        "tp": tp_t,
        "fn": fn,
        "query_tp": tp_q,
        "fp": fp,
        "fp_gt": _num(row.get("FP.gt"), int),
        "fp_al": _num(row.get("FP.al"), int),
        "recall": _num(row.get("METRIC.Recall")),
        "recall_ci": wilson(tp_t, tp_t + fn),
        "precision": _num(row.get("METRIC.Precision")),
        "precision_ci": wilson(tp_q, tp_q + fp),
        "f1": _num(row.get("METRIC.F1_Score")),
        "f1_ci": f1_interval(tp_t, fn, tp_q, fp),
        "truth_titv": _num(row.get("TRUTH.TOTAL.TiTv_ratio")),
        "query_titv": _num(row.get("QUERY.TOTAL.TiTv_ratio")),
        "truth_het_hom": _num(row.get("TRUTH.TOTAL.het_hom_ratio")),
        "query_het_hom": _num(row.get("QUERY.TOTAL.het_hom_ratio")),
    }


def happy_spectrum(vcf_path):
    """Классы замен у PASS TP и FP (QUERY) и у FN (TRUTH) в размеченном VCF hap.py."""
    counts = {"TP": {}, "FP": {}, "FN": {}}
    if not vcf_path:
        return counts
    with gzip.open(vcf_path, "rt") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            f = line.rstrip("\n").split("\t")
            ref, alts = f[3].upper(), f[4].upper().split(",")
            if len(ref) != 1 or len(alts) != 1 or len(alts[0]) != 1:
                continue
            if ref not in COMPLEMENT or alts[0] not in COMPLEMENT:
                continue
            keys = f[8].split(":")
            truth = dict(zip(keys, f[9].split(":")))
            query = dict(zip(keys, f[10].split(":")))
            cls = snv_class(ref, alts[0])
            if query.get("BD") in ("TP", "FP") and f[6] in ("PASS", "."):
                counts[query["BD"]][cls] = counts[query["BD"]].get(cls, 0) + 1
            if truth.get("BD") == "FN":
                counts["FN"][cls] = counts["FN"].get(cls, 0) + 1
    return counts


# ----------------------------------------------------------------- сборка данных


def collect(args):
    rep = {
        "sample": args.sample,
        "threads": args.threads,
        "mpileup_profile": args.mpileup_profile,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checks": [],
    }

    versions = []
    if args.versions and os.path.exists(args.versions):
        with open(args.versions) as fh:
            versions = [line.rstrip("\n").split("\t", 1) for line in fh if line.strip()]
    versions.append(["hap.py", "0.3.15 (quay.io/biocontainers, закреплён по digest)"])
    rep["versions"] = dict(versions)

    steps = [load_json(p) for p in args.metrics]
    steps.sort(key=lambda s: (STEP_ORDER.index(s["step"]) if s["step"] in STEP_ORDER else len(STEP_ORDER), s["step"]))
    for s in steps:
        # Командная строка (пути staging-каталогов cwltool) и имя узла/контейнера остаются в
        # <step>.metrics.json для отладки; в отчёт они не идут.
        s.pop("cmd", None)
        s.pop("host", None)
        # рекомендация для --mem: пик x1.5, кратно 256 МБ, не меньше 512 МБ
        s["suggested_mem_mb"] = max(512, int(math.ceil(s["peak_rss_mb"] * 1.5 / 256.0)) * 256)
    rep["steps"] = steps
    rep["totals"] = {
        "wall_s": sum(s["wall_s"] for s in steps),
        "cpu_s": sum(s["user_s"] + s["sys_s"] for s in steps),
        "max_peak_rss_mb": max([s["peak_rss_mb"] for s in steps] or [0]),
    }

    # --- риды
    fastp = load_json(args.fastp) or {}
    before = fastp.get("summary", {}).get("before_filtering", {})
    after = fastp.get("summary", {}).get("after_filtering", {})
    rep["reads"] = {
        "pairs_before": (before.get("total_reads") or 0) // 2,
        "pairs_after": (after.get("total_reads") or 0) // 2,
        "q30_before": before.get("q30_rate"),
        "q30_after": after.get("q30_rate"),
        "gc": before.get("gc_content"),
        "duplication_rate_fastp": fastp.get("duplication", {}).get("rate"),
        # Пик длины вставки из fastp не берётся: fastp 1.4.0 считает его только в рабочем
        # потоке 0, по ~1/N пар, и значение меняется с числом потоков (D-23). Длина вставки
        # по всем парам есть ниже, из samtools stats.
        "adapter_trimmed_reads": fastp.get("adapter_cutting", {}).get("adapter_trimmed_reads"),
        "too_short_reads": fastp.get("filtering_result", {}).get("too_short_reads"),
    }

    # --- выравнивание
    sn, cov = parse_samtools_stats(args.samtools_stats)
    qcp = (load_json(args.flagstat) or {}).get("QC-passed reads", {})
    mdup = load_json(args.markdup) or {}
    covrows = parse_coverage_tsv(args.coverage)
    contig_len = sum(int(r["endpos"]) - int(r["startpos"]) + 1 for r in covrows) if covrows else 0
    aln = {
        "mapped_pct": _num(qcp.get("mapped %")),
        "properly_paired_pct": _num(qcp.get("properly paired %")),
        "error_rate": sn.get("error rate"),
        "insert_size_mean": sn.get("insert size average"),
        "insert_size_sd": sn.get("insert size standard deviation"),
        "mean_depth": (
            sum(float(r["meandepth"]) * (int(r["endpos"]) - int(r["startpos"]) + 1) for r in covrows) / contig_len
        )
        if contig_len
        else None,
        "breadth_pct": float(covrows[0]["coverage"]) if len(covrows) == 1 else None,
        "contig_len": contig_len,
    }
    # В JSON samtools markdup все счётчики — в ридах (PAIRED = риды из пар), поэтому
    # доля дубликатов = DUPLICATE PAIR / PAIRED, без деления на 2 (docs/DEBUGGING.md, D-06).
    if mdup.get("PAIRED"):
        aln["dup_rate"] = mdup.get("DUPLICATE PAIR", 0) / float(mdup["PAIRED"])
        aln["optical_dup_rate"] = mdup.get("DUPLICATE PAIR OPTICAL", 0) / float(mdup["PAIRED"])
        aln["library_dup_rate"] = aln["dup_rate"] - aln["optical_dup_rate"]
        aln["estimated_library_size"] = mdup.get("ESTIMATED_LIBRARY_SIZE")
    if cov and contig_len:
        hist = {0: max(0, contig_len - sum(n for _, n in cov))}
        for d, n in cov:
            hist[d] = hist.get(d, 0) + n
        tot = float(sum(hist.values()))
        m = sum(d * n for d, n in hist.items()) / tot
        var = sum(n * (d - m) ** 2 for d, n in hist.items()) / tot
        top = int(m * 2.5) + 1
        aln["depth"] = {
            "mean": m,
            "variance": var,
            "dispersion_index": var / m if m else None,
            "hist": [[d, hist.get(d, 0) / tot] for d in range(0, top + 1)],
            "poisson": [[d, math.exp(-m + d * math.log(m) - math.lgamma(d + 1))] for d in range(0, top + 1)],
            "negbin": ([[d, negbin_pmf(d, m, var)] for d in range(0, top + 1)] if var > m else None),
            "thresholds": [
                {
                    "lt": k,
                    "observed": sum(n for d, n in hist.items() if d < k) / tot,
                    "poisson": poisson_cdf_below(k, m),
                    "negbin": negbin_cdf_below(k, m, var),
                }
                for k in (10, 15, 20)
            ],
        }
    rep["alignment"] = aln

    # --- варианты
    bst = parse_bcftools_stats(args.bcftools_stats)
    calls = {
        "snps": bst["SN"].get("number of SNPs"),
        "indels": bst["SN"].get("number of indels"),
        "records": bst["SN"].get("number of records"),
        "ts_tv": bst["TSTV"]["ts_tv"] if bst["TSTV"] else None,
    }
    if bst["PSC"]:
        calls.update(
            het=bst["PSC"]["het"],
            hom_alt=bst["PSC"]["nonref_hom"],
            het_hom_ratio=(bst["PSC"]["het"] / float(bst["PSC"]["nonref_hom"]) if bst["PSC"]["nonref_hom"] else None),
        )
    six = dict.fromkeys(SNV_CLASSES, 0)
    for k, v in bst["ST"].items():
        ref, alt = k.split(">")
        six[snv_class(ref, alt)] += v
    calls["spectrum"] = six
    rep["calls"] = calls

    # --- сверка с эталонами
    bench = {}
    n = len(args.happy_names)
    for name, summ, ext, vcf in zip(
        args.happy_names, args.happy_summary, args.happy_extended or [None] * n, args.happy_vcf or [None] * n
    ):
        rows = [benchmark_row(r) for r in read_csv(summ)]
        strata = []
        if ext:
            strata = [
                benchmark_row(r)
                for r in read_csv(ext)
                if r.get("Subtype") == "*"
                and r.get("Genotype", "*") == "*"
                and r.get("QQ", "*") == "*"
                and r.get("Filter") == "PASS"
                and r.get("Subset") not in ("*", "TS_contained", "TS_boundary")
            ]
        spec = happy_spectrum(vcf)
        ca_fp, ca_tp = spec["FP"].get("C>A", 0), spec["TP"].get("C>A", 0)
        oth_fp, oth_tp = sum(spec["FP"].values()) - ca_fp, sum(spec["TP"].values()) - ca_tp
        oxog = {
            "fp_c2a": ca_fp,
            "fp_total": ca_fp + oth_fp,
            "tp_c2a": ca_tp,
            "tp_total": ca_tp + oth_tp,
            "fisher_p": (
                fisher_exact_two_sided(ca_fp, oth_fp, ca_tp, oth_tp) if (ca_fp + oth_fp) and (ca_tp + oth_tp) else None
            ),
        }
        bench[name] = {"summary": rows, "strata": strata, "spectrum": spec, "oxog": oxog}
    rep["benchmark"] = bench

    # --- порог качества (QC gate)
    thr = load_json(args.thresholds) or {}

    def check(name, value, op, limit):
        ok = value is not None and (value >= limit if op == ">=" else value <= limit)
        rep["checks"].append({"name": name, "value": value, "op": op, "limit": limit, "pass": ok})

    for tname, per_type in thr.get("happy", {}).items():
        if tname not in bench:
            continue
        for vtype, lim in per_type.items():
            row = next((r for r in bench[tname]["summary"] if r["type"] == vtype and r["filter"] == "PASS"), None)
            for metric in ("recall", "precision", "f1"):
                if metric in lim:
                    check("%s %s PASS %s" % (tname, vtype, metric), row and row[metric], ">=", lim[metric])
    qc_values = {
        "mapped_pct": aln.get("mapped_pct"),
        "mean_depth": aln.get("mean_depth"),
        "ts_tv": calls.get("ts_tv"),
        "dup_rate": aln.get("dup_rate"),
        "library_dup_rate": aln.get("library_dup_rate"),
        "optical_dup_rate": aln.get("optical_dup_rate"),
    }
    for key, limit in sorted(thr.get("qc", {}).items()):
        op, metric = (">=", key[4:]) if key.startswith("min_") else ("<=", key[4:])
        check(metric, qc_values.get(metric), op, limit)
    rep["qc_pass"] = all(c["pass"] for c in rep["checks"]) if rep["checks"] else None

    # --- масштабирование (порядок величины; допущения — в отчёте)
    if contig_len and aln.get("mean_depth"):
        factor = (GENOME_BP / contig_len) * (30.0 / aln["mean_depth"])
        prod = [s for s in steps if not s["step"].startswith(("happy", "bwa_mem2_index"))]
        cpu_h = sum(s["user_s"] + s["sys_s"] for s in prod) * factor / 3600.0
        rep["scaling"] = {
            "factor": factor,
            "cpu_hours_per_30x_genome_lower_bound": cpu_h,
            "cpu_hours_100k_genomes_lower_bound": cpu_h * 100000,
        }
    return rep


# ----------------------------------------------------------------- markdown


def pct(x, digits=2):
    return "–" if x is None else ("%." + str(digits) + "f %%") % (100 * x)


def fnum(x, digits=3):
    return "–" if x is None else ("%." + str(digits) + "f") % x


def ci(c, digits=4):
    # tuple(): after a JSON round trip the interval is a list, and "%" needs a tuple
    return "–" if not c or c[0] is None else ("[%." + str(digits) + "f; %." + str(digits) + "f]") % tuple(c)


def md_table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    return "\n".join(out + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows])


STEP_RU = {
    "fastp": "fastp: обрезка и QC ридов",
    "bwa_mem2_index": "bwa-mem2 index + faidx",
    "bwa_mem2_mem": "bwa-mem2 mem | fixmate",
    "samtools_sort": "samtools sort",
    "samtools_markdup": "samtools markdup",
    "samtools_qc": "samtools flagstat/stats/coverage",
    "bcftools_call": "bcftools mpileup | call",
    "bcftools_filter": "bcftools norm | filter",
    "bcftools_stats": "bcftools stats",
}


def step_label(name):
    if name.startswith("happy_"):
        return "hap.py против " + name[len("happy_") :]
    return STEP_RU.get(name, name)


def render_markdown(rep):
    md = []
    verdict = {True: "пройден", False: "не пройден", None: "пороги не заданы"}[rep["qc_pass"]]
    md.append("# Отчёт mini-WGS: %s\n" % rep["sample"])
    md.append(
        "Сформирован %s · потоков %s · профиль mpileup `%s` · **порог качества: %s**\n"
        % (rep["generated_utc"], rep["threads"], rep["mpileup_profile"] or "по умолчанию", verdict)
    )

    if rep["checks"]:
        md.append("## Порог качества\n")
        md.append(
            md_table(
                ["проверка", "значение", "граница", "итог"],
                [
                    [c["name"], fnum(c["value"], 4), "%s %s" % (c["op"], c["limit"]), "да" if c["pass"] else "нет"]
                    for c in rep["checks"]
                ],
            )
        )
        md.append("")

    md.append("## Сверка с эталонами GIAB (hap.py)\n")
    md.append(
        "Recall = TP/(TP+FN), precision = TP/(TP+FP). В скобках 95% интервалы: Уилсона для долей, "
        "Монте-Карло по апостериорным Beta для F1. В регионе 2 Мб несколько сотен инделов, поэтому "
        "сравнивать прогоны нужно по интервалам, а не по точечным оценкам.\n"
    )
    for name, b in rep["benchmark"].items():
        md.append("### %s\n" % name)
        md.append(
            md_table(
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
                        r["type"],
                        r["filter"],
                        r["truth_total"],
                        r["tp"],
                        r["fn"],
                        r["fp"],
                        "%s %s" % (fnum(r["recall"], 4), ci(r["recall_ci"])),
                        "%s %s" % (fnum(r["precision"], 4), ci(r["precision_ci"])),
                        "%s %s" % (fnum(r["f1"], 4), ci(r["f1_ci"])),
                    ]
                    for r in b["summary"]
                ],
            )
        )
        snp = next((r for r in b["summary"] if r["type"] == "SNP" and r["filter"] == "PASS"), None)
        if snp and snp["truth_titv"]:
            md.append(
                "\nSNP: Ti/Tv эталона %s, вызова %s; het/hom эталона %s, вызова %s.\n"
                % (
                    fnum(snp["truth_titv"], 2),
                    fnum(snp["query_titv"], 2),
                    fnum(snp["truth_het_hom"], 2),
                    fnum(snp["query_het_hom"], 2),
                )
            )
        if b["strata"]:
            md.append("\n**По стратификациям GIAB v3.6 (PASS)**\n")
            md.append(
                md_table(
                    ["страта", "тип", "в эталоне", "recall [95% ДИ]", "precision [95% ДИ]", "F1"],
                    [
                        [
                            r["subset"],
                            r["type"],
                            r["truth_total"],
                            "%s %s" % (fnum(r["recall"], 3), ci(r["recall_ci"], 3)),
                            "%s %s" % (fnum(r["precision"], 3), ci(r["precision_ci"], 3)),
                            fnum(r["f1"], 3),
                        ]
                        for r in sorted(b["strata"], key=lambda x: (x["subset"], x["type"]))
                        if r["truth_total"] or r["fp"]
                    ],
                )
            )
        ox = b["oxog"]
        if ox["fisher_p"] is not None:
            md.append(
                "\nПроверка на 8-oxoG: доля C>A среди PASS FP SNV %d/%d, среди TP %d/%d, тест Фишера "
                "p = %.3g. Окислительный артефакт дал бы избыток C>A среди FP и малое p.\n"
                % (ox["fp_c2a"], ox["fp_total"], ox["tp_c2a"], ox["tp_total"], ox["fisher_p"])
            )
        md.append("")

    r, a, c = rep["reads"], rep["alignment"], rep["calls"]
    md.append("## Риды (fastp)\n")
    md.append(
        md_table(
            ["метрика", "значение"],
            [
                ["пар ридов (до → после)", "%s → %s" % (r["pairs_before"], r["pairs_after"])],
                ["оснований с Q30 (до → после)", "%s → %s" % (pct(r["q30_before"]), pct(r["q30_after"]))],
                ["GC", pct(r["gc"])],
                [
                    "ридов с обрезанным адаптером",
                    r["adapter_trimmed_reads"] if r["adapter_trimmed_reads"] is not None else "–",
                ],
                ["дубликаты (оценка fastp)", pct(r["duplication_rate_fastp"])],
            ],
        )
    )
    md.append("\n## Выравнивание (bwa-mem2, samtools)\n")
    md.append(
        md_table(
            ["метрика", "значение"],
            [
                ["картировано", "%s %%" % fnum(a["mapped_pct"], 2)],
                ["в правильных парах", "%s %%" % fnum(a["properly_paired_pct"], 2)],
                ["доля несовпадений с референсом (вместе с настоящими вариантами)", fnum(a["error_rate"], 5)],
                [
                    "длина вставки, среднее ± sd",
                    "%s ± %s" % (fnum(a["insert_size_mean"], 1), fnum(a["insert_size_sd"], 1)),
                ],
                ["средняя глубина без дубликатов", "%sx" % fnum(a["mean_depth"], 1)],
                [
                    "дубликаты: всего / оптические / библиотечные (ПЦР)",
                    "%s / %s / %s"
                    % (pct(a.get("dup_rate")), pct(a.get("optical_dup_rate")), pct(a.get("library_dup_rate"))),
                ],
            ],
        )
    )
    if a.get("depth"):
        d = a["depth"]
        md.append(
            "\nГлубина: среднее %.1f, дисперсия %.1f, индекс дисперсии %.2f (1 — Пуассон; больше 1 — "
            "сверхдисперсия, как у реальных библиотек).\n" % (d["mean"], d["variance"], d["dispersion_index"])
        )
        md.append(
            md_table(
                ["глубина <", "наблюдаемая доля", "Пуассон", "отриц. биномиальное"],
                [[t["lt"], pct(t["observed"], 3), pct(t["poisson"], 3), pct(t["negbin"], 3)] for t in d["thresholds"]],
            )
        )
        md.append(
            "\nКрая региона проседают: риды взяты только из региона, поэтому BED эталонов обрезаны на "
            "EDGE_MARGIN с каждой стороны.\n"
        )

    md.append("\n## Варианты (bcftools, PASS)\n")
    md.append(
        md_table(
            ["метрика", "значение"],
            [
                ["SNP / инделы", "%s / %s" % (c["snps"], c["indels"])],
                ["Ti/Tv (для WGS ожидается ≈ 2,0–2,1)", fnum(c["ts_tv"], 2)],
                [
                    "het / hom-alt",
                    "%s / %s (отношение %s)" % (c.get("het"), c.get("hom_alt"), fnum(c.get("het_hom_ratio"), 2)),
                ],
                ["спектр замен", ", ".join("%s %d" % (k, v) for k, v in c["spectrum"].items())],
            ],
        )
    )

    md.append("\n## Ресурсы по шагам\n")
    md.append(
        md_table(
            [
                "шаг",
                "время, с",
                "CPU, с",
                "CPU %",
                "потоки",
                "эффективность",
                "пик RSS, МБ",
                "крупнейший процесс, МБ",
                "чтение / запись, МБ",
                "--mem для Slurm",
            ],
            [
                [
                    step_label(s["step"]),
                    fnum(s["wall_s"], 1),
                    fnum(s["user_s"] + s["sys_s"], 1),
                    fnum(s["cpu_pct"], 0),
                    s.get("threads") or "–",
                    fnum(s.get("cpu_efficiency"), 2),
                    fnum(s["peak_rss_mb"], 0),
                    fnum(s["max_rss_mb"], 0),
                    "%s / %s" % (fnum(s.get("io_read_mb"), 0), fnum(s.get("io_write_mb"), 0)),
                    "%dM" % s["suggested_mem_mb"],
                ]
                for s in rep["steps"]
            ],
        )
    )
    t = rep["totals"]
    md.append(
        "\nИтого при последовательном запуске: %.1f с, CPU %.1f с, максимальный пик RSS %.0f МБ. Пик RSS — "
        "максимум из крупнейшего процесса и суммы по дереву процессов (bin/measure.py). "
        "--mem = пик × 1,5, кратно 256 МБ.\n" % (t["wall_s"], t["cpu_s"], t["max_peak_rss_mb"])
    )
    if rep.get("scaling"):
        sc = rep["scaling"]
        md.append(
            "Порядок величины для генома 30x (×%.0f по числу оснований, только шаги с линейным временем, без "
            "индексации и hap.py): **не меньше ≈ %.0f CPU-часов на геном**, ≈ %.1f млн CPU-часов на 100 000 "
            "геномов. Это нижняя оценка: выравнивание на полный GRCh38 медленнее на рид (индекс не помещается "
            "в кэш, больше кандидатов на рид). Память так не масштабируется: индексу bwa-mem2 для GRCh38 "
            "нужно ~10–16 ГБ при любой глубине.\n"
            % (sc["factor"], sc["cpu_hours_per_30x_genome_lower_bound"], sc["cpu_hours_100k_genomes_lower_bound"] / 1e6)
        )

    md.append("\n## Версии\n")
    md.append(md_table(["инструмент", "версия"], [[k, v] for k, v in rep["versions"].items()]))
    return "\n".join(md) + "\n"


# ----------------------------------------------------------------- main


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--sample", required=True)
    p.add_argument("--metrics", nargs="+", default=[])
    p.add_argument("--fastp")
    p.add_argument("--markdup")
    p.add_argument("--flagstat")
    p.add_argument("--samtools-stats")
    p.add_argument("--coverage")
    p.add_argument("--bcftools-stats")
    p.add_argument("--happy-names", nargs="*", default=[])
    p.add_argument("--happy-summary", nargs="*", default=[])
    p.add_argument("--happy-extended", nargs="*", default=[])
    p.add_argument("--happy-vcf", nargs="*", default=[])
    p.add_argument("--thresholds")
    p.add_argument("--versions", default="/opt/hts/TOOL_VERSIONS.tsv")
    p.add_argument("--threads", type=int)
    p.add_argument("--mpileup-profile", default="")
    p.add_argument("--out-md", default="report.md")
    p.add_argument("--out-html", default="report.html")
    p.add_argument("--out-json", default="report.json")
    p.add_argument("--out-tsv", default="step_metrics.tsv")
    return p.parse_args(argv)


def write_outputs(rep, args):
    with open(args.out_md, "w", encoding="utf-8") as fh:
        fh.write(render_markdown(rep))
    with open(args.out_json, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    cols = [
        "step",
        "exit_code",
        "wall_s",
        "user_s",
        "sys_s",
        "cpu_pct",
        "threads",
        "cpu_efficiency",
        "max_rss_mb",
        "tree_rss_peak_mb",
        "peak_rss_mb",
        "suggested_mem_mb",
        "io_read_mb",
        "io_write_mb",
    ]
    with open(args.out_tsv, "w", encoding="utf-8") as fh:
        fh.write("\t".join(cols) + "\n")
        for s in rep["steps"]:
            fh.write("\t".join("" if s.get(k) is None else str(s.get(k)) for k in cols) + "\n")
    if args.out_html:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import render_html  # noqa: E402  (рядом с этим файлом; в CWL оба скрипта в рабочем каталоге)

        with open(args.out_html, "w", encoding="utf-8") as fh:
            fh.write(render_html.render(rep))


def main(argv=None):
    args = parse_args(argv)
    if len(args.happy_names) != len(args.happy_summary):
        sys.exit("ошибка: --happy-names и --happy-summary разной длины")
    write_outputs(collect(args), args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
