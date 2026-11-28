#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Отчёт RNA-seq: качество образцов, сверка с эталоном ERCC, ресурсы шагов.

    python3 rnaseq_report.py --samples UHR_Rep1 ... --groups UHR ... --mixes Mix1 ... \\
        --counts featureCounts.txt --counts-summary featureCounts.txt.summary \\
        --star-logs S.Log.final.out ... --star-gene-counts S.ReadsPerGene.out.tab ... \\
        --fastp-json S.fastp.json ... --ercc ercc_concentrations.tsv --annotation genes.gtf \\
        --strandedness 2 --step-metrics *.metrics.json [--qc-thresholds rnaseq_qc_thresholds.json] \\
        --out-prefix rnaseq

Эталон RNA-seq — 92 синтетических транскрипта ERCC с известной концентрацией в двух
смесях: Mix 1 (в образцах UHR) и Mix 2 (в HBR). По ним проверяются две вещи:

  * линейность: log2(фрагменты на килобазу) против log2(концентрации) в каждом образце;
    у линейного метода наклон 1. Интервал наклона — бутстреп по транскриптам с
    фиксированным зерном, поэтому отчёт воспроизводим;
  * точность кратности: log2(UHR / HBR) каждого ERCC против известного log2(Mix 1 / Mix 2)
    в четырёх подгруппах (4, 1, 2/3, 1/2). Нормировка на число фрагментов генов
    (библиотеку) сдвигает все отношения ERCC на одну константу, потому что доля мРНК в
    двух образцах разная. Сдвиг оценивается по подгруппе B (ожидается 1:1) и
    вычитается; он сам выводится в отчёт.

Скрипт подключается в CWL через $include, поэтому он самодостаточен: только
стандартная библиотека Python 3, без выражений CWL в тексте.
"""

import argparse
import csv
import json
import math
import os
import random
import re
import sys

ERCC_PREFIX = "ERCC-"
MIN_FIT_COUNT = 10  # фрагментов: ниже пуассоновский шум > 30 %
BOOTSTRAP = 2000
SEED = 20261125
# Ожидаемое направление UHR/HBR по биологии образцов: UHR — смесь 10 линий опухолевых
# клеток (делятся), HBR — мозг взрослых доноров (нейроны). Гены chr22.
MARKERS = (
    ("NEFH", "HBR", "нейрофиламент, тяжёлая цепь: нейроны"),
    ("SYN3", "HBR", "синапсин III: синапсы"),
    ("CACNG2", "HBR", "старгазин, субъединица AMPA-рецепторов"),
    ("SEPTIN3", "HBR", "септин 3: нейроны"),
    ("MCM5", "UHR", "лицензирование репликации ДНК: делящиеся клетки"),
    ("CDC45", "UHR", "инициация репликации: делящиеся клетки"),
    ("CHEK2", "UHR", "контрольная точка клеточного цикла"),
    ("PRAME", "UHR", "раково-тестикулярный антиген: опухолевые линии"),
)
STRAND_NAMES = {0: "unstranded", 1: "forward", 2: "reverse"}


# ----------------------------------------------------------------- чтение файлов


def read_ercc_table(path):
    """ERCC id -> подгруппа, концентрации в Mix 1 и Mix 2 (аттомоль/мкл), log2(Mix1/Mix2)."""
    out = {}
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.reader(fh, delimiter="\t"))
    for r in rows[1:]:
        if len(r) < 5 or not r[1].startswith(ERCC_PREFIX):
            continue
        mix1, mix2 = float(r[3]), float(r[4])
        out[r[1]] = {"subgroup": r[2], "Mix1": mix1, "Mix2": mix2, "log2_ratio": math.log2(mix1 / mix2)}
    return out


def read_featurecounts(path):
    """featureCounts -o: (имена колонок образцов, {gene_id: {"length": int, "counts": [int, ...]}})."""
    genes, columns = {}, None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            f = line.rstrip("\n").split("\t")
            if columns is None:
                columns = f[6:]
                continue
            genes[f[0]] = {"length": int(f[5]), "counts": [int(x) for x in f[6:]]}
    return columns, genes


def read_featurecounts_summary(path):
    """featureCounts .summary: {колонка: {статус: число}}."""
    with open(path, encoding="utf-8") as fh:
        rows = [line.rstrip("\n").split("\t") for line in fh if line.strip()]
    cols = rows[0][1:]
    return {c: {r[0]: int(r[i + 1]) for r in rows[1:]} for i, c in enumerate(cols)}


def read_star_log(path):
    """Log.final.out STAR: нужные поля как числа (проценты — в процентах)."""
    keys = {
        "Number of input reads": "input_pairs",
        "Uniquely mapped reads number": "unique",
        "Uniquely mapped reads %": "unique_pct",
        "% of reads mapped to multiple loci": "multi_pct",
        "% of reads mapped to too many loci": "too_many_pct",
        "% of reads unmapped: too short": "unmapped_short_pct",
        "% of reads unmapped: other": "unmapped_other_pct",
        "% of chimeric reads": "chimeric_pct",
        "Mismatch rate per base, %": "mismatch_pct",
        "Deletion rate per base": "deletion_pct",
        "Insertion rate per base": "insertion_pct",
        "Number of splices: Total": "splices",
        "Number of splices: Annotated (sjdb)": "splices_annotated",
        "Number of splices: Non-canonical": "splices_noncanonical",
        "Average input read length": "read_length_pair",
    }
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if "|" not in line:
                continue
            k, v = (x.strip() for x in line.split("|", 1))
            if k in keys:
                out[keys[k]] = float(v.rstrip("%"))
    for k in ("input_pairs", "unique", "splices", "splices_annotated", "splices_noncanonical"):
        if k in out:
            out[k] = int(out[k])
    return out


def read_star_gene_counts(path):
    """ReadsPerGene.out.tab: ({N_*: (u, f, r)}, {gene_id: (u, f, r)}).

    Колонки STAR: без учёта цепи; рид 1 на цепи транскрипта (htseq-count -s yes);
    рид 2 на цепи транскрипта (-s reverse)."""
    special, genes = {}, {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            f = line.split()
            if len(f) < 4:
                continue
            row = (int(f[1]), int(f[2]), int(f[3]))
            (special if f[0].startswith("N_") else genes)[f[0]] = row
    return special, genes


def read_fastp(path):
    """Сводка fastp. Пик длины вставки не берётся: fastp 1.4.0 считает его только в рабочем
    потоке 0, то есть по ~1/N пар, и значение зависит от числа потоков (D-23)."""
    with open(path, encoding="utf-8") as fh:
        js = json.load(fh)
    s = js["summary"]
    return {
        "pairs_before": s["before_filtering"]["total_reads"] // 2,
        "pairs_after": s["after_filtering"]["total_reads"] // 2,
        "q30_rate": s["after_filtering"].get("q30_rate"),
        "gc_content": s["after_filtering"].get("gc_content"),
        "duplication_rate": js.get("duplication", {}).get("rate"),
        "adapter_trimmed_reads": js.get("adapter_cutting", {}).get("adapter_trimmed_reads"),
    }


GTF_ATTR = re.compile(r'(\w+) "([^"]*)"')


def read_gtf_genes(path):
    """gene_id -> {"name", "type"} из записей gene (у ERCC — из exon)."""
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            f = line.rstrip("\n").split("\t")
            if len(f) < 9 or f[2] not in ("gene", "exon"):
                continue
            attrs = dict(GTF_ATTR.findall(f[8]))
            gid = attrs.get("gene_id")
            if gid and (f[2] == "gene" or gid not in out):
                out[gid] = {"name": attrs.get("gene_name", gid), "type": attrs.get("gene_type", "")}
    return out


STAGES = ("star_index", "fastp", "star_align", "bam_finalize", "featurecounts")


def read_step_metrics(paths, samples=()):
    """Метрики шагов в порядке пайплайна: индекс, fastp и STAR по образцам, featureCounts."""
    keep = ("step", "wall_s", "user_s", "sys_s", "peak_rss_mb", "threads", "exit_code")
    out = []
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            m = json.load(fh)
        out.append({k: m.get(k) for k in keep})

    def order(step):
        name = step["step"] or ""
        stage = next((i for i, s in enumerate(STAGES) if name == s or name.startswith(s + "_")), len(STAGES))
        sample = name[len(STAGES[stage]) + 1 :] if stage < len(STAGES) else name
        return (stage, list(samples).index(sample) if sample in samples else len(samples), name)

    return sorted(out, key=order)


# ----------------------------------------------------------------- статистика


def mean(xs):
    return sum(xs) / float(len(xs)) if xs else None


def median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = mean(xs), mean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def ols(xs, ys):
    """Наклон, свободный член и R² прямой y = a + b x (наименьшие квадраты)."""
    mx, my = mean(xs), mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    r = pearson(xs, ys)
    return slope, my - slope * mx, (r * r if r is not None else None)


def bootstrap_slope_ci(xs, ys, n=BOOTSTRAP, seed=SEED):
    """95 % интервал наклона: перцентили наклона по выборкам транскриптов с возвращением."""
    rng = random.Random(seed)
    idx = range(len(xs))
    slopes = []
    for _ in range(n):
        pick = [rng.choice(idx) for _ in idx]
        bx = [xs[i] for i in pick]
        if max(bx) == min(bx):
            continue
        slopes.append(ols(bx, [ys[i] for i in pick])[0])
    slopes.sort()
    return slopes[int(0.025 * len(slopes))], slopes[int(0.975 * len(slopes)) - 1]


def rmse(errors):
    return math.sqrt(sum(e * e for e in errors) / len(errors)) if errors else None


# ----------------------------------------------------------------- расчёты


def strandedness(gene_counts, configured):
    """Доля стрендовых отсчётов на каждой цепи и вывод о типе библиотеки по счётчику STAR."""
    fwd = sum(v[1] for v in gene_counts.values())
    rev = sum(v[2] for v in gene_counts.values())
    share_rev = rev / float(fwd + rev) if fwd + rev else None
    if share_rev is None:
        inferred = None
    elif share_rev >= 0.9:
        inferred = 2
    elif share_rev <= 0.1:
        inferred = 1
    else:
        inferred = 0
    share_cfg = {0: None, 1: 1 - share_rev if share_rev is not None else None, 2: share_rev}[configured]
    return {
        "forward_fragments": fwd,
        "reverse_fragments": rev,
        "reverse_share": share_rev,
        "inferred": inferred,
        "inferred_name": STRAND_NAMES.get(inferred),
        "configured": configured,
        "configured_name": STRAND_NAMES[configured],
        "configured_share": share_cfg,
        "matches": inferred == configured,
    }


def counter_agreement(fc_genes, column, star_genes, strand):
    """featureCounts против счётчика STAR на тех же BAM: сумма и корреляция log2(n+1) по генам."""
    ids = sorted(set(fc_genes) & set(star_genes))
    a = [fc_genes[g]["counts"][column] for g in ids]
    b = [star_genes[g][strand] for g in ids]
    both = [(x, y) for x, y in zip(a, b) if x or y]
    r = pearson([math.log2(x + 1) for x, _ in both], [math.log2(y + 1) for _, y in both])
    sa, sb = sum(a), sum(b)
    ercc = [g for g in ids if g.startswith(ERCC_PREFIX)]
    return {
        "genes_compared": len(both),
        "featurecounts_total": sa,
        "star_total": sb,
        "total_diff_pct": 100.0 * (sa - sb) / sb if sb else None,
        "pearson_log2": r,
        "ercc_identical": all(fc_genes[g]["counts"][column] == star_genes[g][strand] for g in ercc),
    }


def dose_response(counts, lengths, conc):
    """Линейность по ERCC одного образца: log2(фрагменты/кб) против log2(аттомоль/мкл)."""
    ids = sorted(conc)
    detected = [e for e in ids if counts.get(e, 0) > 0]
    fit = [e for e in ids if counts.get(e, 0) >= MIN_FIT_COUNT]
    xs = [math.log2(conc[e]) for e in fit]
    ys = [math.log2(counts[e] / (lengths[e] / 1000.0)) for e in fit]
    slope, intercept, r2 = ols(xs, ys)
    lo, hi = bootstrap_slope_ci(xs, ys)
    return {
        "ercc_total": len(ids),
        "detected": len(detected),
        "fitted": len(fit),
        "slope": slope,
        "slope_ci": [lo, hi],
        "intercept": intercept,
        "r2": r2,
        "min_detected_conc": min(conc[e] for e in detected) if detected else None,
        "dynamic_range_log10": (
            math.log10(max(conc[e] for e in detected) / min(conc[e] for e in detected)) if detected else None
        ),
        # для графика: ERCC, аттомоль/мкл, фрагменты, длина
        "points": [[e, conc[e], counts.get(e, 0), lengths[e]] for e in ids],
    }


def detection_limit(per_sample_counts, conc):
    """Наименьшая концентрация, с которой и выше все ERCC видны (≥ 1 фрагмента) во всех репликах."""
    levels = sorted(set(conc.values()))
    limit = None
    for c in reversed(levels):
        ids = [e for e in conc if conc[e] >= c]
        if all(counts.get(e, 0) > 0 for counts in per_sample_counts for e in ids):
            limit = c
        else:
            break
    return limit


def ercc_fold_change(table, norm_a, norm_b, raw_a, raw_b):
    """log2(A/B) по ERCC против ожидаемого log2(Mix1/Mix2); A — образцы с Mix 1, B — с Mix 2.

    norm_* — списки {ERCC: фрагменты на миллион фрагментов генов} по репликам, raw_* — сырые
    фрагменты (для отбора: ≥ MIN_FIT_COUNT в каждой реплике обеих групп)."""
    rows = []
    for e in sorted(table):
        if not all(r.get(e, 0) >= MIN_FIT_COUNT for r in raw_a + raw_b):
            continue
        obs = math.log2(mean([r[e] for r in norm_a]) / mean([r[e] for r in norm_b]))
        rows.append({"ercc": e, "subgroup": table[e]["subgroup"], "expected": table[e]["log2_ratio"], "observed": obs})
    b = [r["observed"] for r in rows if r["subgroup"] == "B"]
    offset = median(b) if b else 0.0
    for r in rows:
        r["adjusted"] = r["observed"] - offset
    groups = {}
    for g in sorted({r["subgroup"] for r in rows}):
        sub = [r for r in rows if r["subgroup"] == g]
        exp = sub[0]["expected"]
        errs = [r["adjusted"] - r["expected"] for r in sub]
        groups[g] = {
            "n": len(sub),
            "expected_log2": exp,
            "expected_ratio": 2**exp,
            "median_adjusted": median([r["adjusted"] for r in sub]),
            "median_observed": median([r["observed"] for r in sub]),
            "bias": median(errs),
            "rmse": rmse(errs),
        }
    all_errs = [r["adjusted"] - r["expected"] for r in rows]
    return {
        "n": len(rows),
        "offset_log2": offset,
        "offset_ratio": 2**offset,
        "pearson": pearson([r["expected"] for r in rows], [r["adjusted"] for r in rows]),
        "rmse": rmse(all_errs),
        "max_abs_subgroup_bias": max(abs(g["bias"]) for g in groups.values()) if groups else None,
        "subgroups": groups,
        "rows": rows,
    }


def replicate_correlation(cpm, raw, samples, groups):
    """Пирсон log2(CPM+1) внутри групп и между ними по генам с ≥ MIN_FIT_COUNT фрагментов во всех образцах.

    Отбор по числу фрагментов, а не по CPM: в маленькой библиотеке CPM ≥ 1 — это один-два
    рида, и пуассоновский шум таких генов занизил бы корреляцию реплик."""
    genes = [g for g in cpm if all(v >= MIN_FIT_COUNT for v in raw[g])]
    logv = {s: [math.log2(cpm[g][i] + 1) for g in genes] for i, s in enumerate(samples)}
    within, between = [], []
    for i in range(len(samples)):
        for j in range(i + 1, len(samples)):
            r = pearson(logv[samples[i]], logv[samples[j]])
            (within if groups[i] == groups[j] else between).append({"a": samples[i], "b": samples[j], "pearson": r})
    return {
        "genes": len(genes),
        "within": within,
        "between": between,
        "min_within": min(x["pearson"] for x in within) if within else None,
        "max_between": max(x["pearson"] for x in between) if between else None,
    }


# ----------------------------------------------------------------- отчёт


def build(a):
    n = len(a.samples)
    for name in ("groups", "mixes", "star_logs", "star_gene_counts", "fastp_json"):
        if len(getattr(a, name)) != n:
            raise SystemExit("--%s: %d values for %d samples" % (name.replace("_", "-"), len(getattr(a, name)), n))
    table = read_ercc_table(a.ercc)
    columns, fc = read_featurecounts(a.counts)
    summary = read_featurecounts_summary(a.counts_summary)
    names = read_gtf_genes(a.annotation) if a.annotation else {}
    # featureCounts называет колонки по файлам BAM: сопоставляем с образцами по имени
    col_of = {}
    for s in a.samples:
        hits = [i for i, c in enumerate(columns) if os.path.basename(c).split(".")[0] == s]
        if len(hits) != 1:
            raise SystemExit("sample %s: %d featureCounts columns match" % (s, len(hits)))
        col_of[s] = hits[0]

    lengths = {g: v["length"] for g, v in fc.items()}
    endo = [g for g in fc if not g.startswith(ERCC_PREFIX)]
    samples = []
    for i, s in enumerate(a.samples):
        col = col_of[s]
        star = read_star_log(a.star_logs[i])
        special, star_genes = read_star_gene_counts(a.star_gene_counts[i])
        st = summary[columns[col]]
        counted = sum(st.values())
        ercc_frag = sum(fc[g]["counts"][col] for g in fc if g.startswith(ERCC_PREFIX))
        gene_frag = sum(fc[g]["counts"][col] for g in endo)
        samples.append(
            {
                "sample": s,
                "group": a.groups[i],
                "ercc_mix": a.mixes[i],
                "fastp": read_fastp(a.fastp_json[i]),
                "star": star,
                "featurecounts": {
                    "assigned": st.get("Assigned", 0),
                    "assigned_pct": 100.0 * st.get("Assigned", 0) / counted if counted else None,
                    "no_features": st.get("Unassigned_NoFeatures", 0),
                    "ambiguity": st.get("Unassigned_Ambiguity", 0),
                    "multimapping": st.get("Unassigned_MultiMapping", 0),
                    "ercc_fragments": ercc_frag,
                    "gene_fragments": gene_frag,
                    "ercc_share": ercc_frag / float(ercc_frag + gene_frag) if ercc_frag + gene_frag else None,
                    "genes_detected_10": sum(1 for g in endo if fc[g]["counts"][col] >= 10),
                },
                "strandedness": strandedness(star_genes, a.strandedness),
                "counter_agreement": counter_agreement(fc, col, star_genes, a.strandedness),
                "star_special": {k: list(v) for k, v in special.items()},
            }
        )

    # CPM по фрагментам генов (без ERCC): ERCC не должны влиять на нормировку генов
    lib = [samples[i]["featurecounts"]["gene_fragments"] for i in range(n)]
    raw_genes = {g: [fc[g]["counts"][col_of[x]] for x in a.samples] for g in endo}
    cpm = {g: [1e6 * fc[g]["counts"][col_of[s]] / lib[i] for i, s in enumerate(a.samples)] for g in endo}
    ercc_cpm = [
        {e: 1e6 * fc[e]["counts"][col_of[s]] / lib[i] for e in table if e in fc} for i, s in enumerate(a.samples)
    ]
    ercc_raw = [{e: fc[e]["counts"][col_of[s]] for e in table if e in fc} for s in a.samples]

    # линейность по образцам и предел обнаружения по группам
    for i, s in enumerate(samples):
        conc = {e: table[e][s["ercc_mix"]] for e in table if e in fc}
        s["ercc_dose_response"] = dose_response(ercc_raw[i], lengths, conc)
    group_names = []
    for g in a.groups:
        if g not in group_names:
            group_names.append(g)
    groups = {}
    for g in group_names:
        idx = [i for i in range(n) if a.groups[i] == g]
        mix = a.mixes[idx[0]]
        conc = {e: table[e][mix] for e in table if e in fc}
        dr = [samples[i]["ercc_dose_response"] for i in idx]
        groups[g] = {
            "samples": [a.samples[i] for i in idx],
            "ercc_mix": mix,
            "detection_limit": detection_limit([ercc_raw[i] for i in idx], conc),
            "mean_slope": mean([d["slope"] for d in dr]),
            "mean_r2": mean([d["r2"] for d in dr]),
        }

    # кратность: группа со смесью Mix1 против группы со смесью Mix2
    by_mix = {groups[g]["ercc_mix"]: g for g in groups}
    fold = None
    if "Mix1" in by_mix and "Mix2" in by_mix:
        ia = [i for i in range(n) if a.groups[i] == by_mix["Mix1"]]
        ib = [i for i in range(n) if a.groups[i] == by_mix["Mix2"]]
        fold = ercc_fold_change(
            table,
            [ercc_cpm[i] for i in ia],
            [ercc_cpm[i] for i in ib],
            [ercc_raw[i] for i in ia],
            [ercc_raw[i] for i in ib],
        )
        fold["numerator"], fold["denominator"] = by_mix["Mix1"], by_mix["Mix2"]

    # биология: маркеры, кратность по CPM генов
    markers = []
    if fold:
        ia = [i for i in range(n) if a.groups[i] == fold["numerator"]]
        ib = [i for i in range(n) if a.groups[i] == fold["denominator"]]
        by_name = {}
        for g in endo:
            by_name.setdefault(names.get(g, {}).get("name", g), []).append(g)
        for name, up, role in MARKERS:
            ids = by_name.get(name, [])
            if len(ids) != 1:
                markers.append({"gene": name, "expected_up": up, "role": role, "found": False})
                continue
            g = ids[0]
            ma, mb = mean([cpm[g][i] for i in ia]), mean([cpm[g][i] for i in ib])
            lfc = math.log2((ma + 1) / (mb + 1))
            observed_up = fold["numerator"] if lfc > 0 else fold["denominator"]
            markers.append(
                {
                    "gene": name,
                    "gene_id": g,
                    "expected_up": up,
                    "role": role,
                    "found": True,
                    "cpm": {fold["numerator"]: ma, fold["denominator"]: mb},
                    "log2fc": lfc,
                    "observed_up": observed_up,
                    "agrees": observed_up == up,
                }
            )

    steps = read_step_metrics(a.step_metrics or [], a.samples)
    totals = {
        "wall_s": sum(s["wall_s"] or 0 for s in steps),
        "cpu_s": sum((s["user_s"] or 0) + (s["sys_s"] or 0) for s in steps),
        "max_peak_rss_mb": max((s["peak_rss_mb"] or 0 for s in steps), default=0),
    }

    rep = {
        "tool": "rnaseq_report.py",
        "threads": a.threads,
        "strandedness": a.strandedness,
        "samples": samples,
        "groups": groups,
        "ercc_fold_change": fold,
        "replicates": replicate_correlation(cpm, raw_genes, a.samples, a.groups),
        "markers": markers,
        "steps": steps,
        "totals": totals,
        "versions": read_versions(a.versions) + fastp_version(a.fastp_json),
        "checks": [],
    }
    rep["checks"] = checks(rep, a.qc_thresholds)
    rep["qc_pass"] = all(c["pass"] for c in rep["checks"]) if rep["checks"] else None
    return rep, fc, names, columns, col_of


def fastp_version(paths):
    """Версия fastp из его JSON (шаг идёт в другом образе, чем отчёт)."""
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            v = json.load(fh).get("summary", {}).get("fastp_version")
        if v:
            return [["fastp", v]]
    return []


def read_versions(paths):
    out = []
    for p in paths or []:
        with open(p, encoding="utf-8") as fh:
            out += [line.rstrip("\n").split("\t") for line in fh if line.strip()]
    return out


def checks(rep, thresholds_path):
    if not thresholds_path:
        return []
    with open(thresholds_path, encoding="utf-8") as fh:
        thr = json.load(fh)["rnaseq"]
    out = []

    def check(name, value, op, limit):
        ok = value is not None and (value >= limit if op == ">=" else value <= limit)
        out.append({"name": name, "value": value, "op": op, "limit": limit, "pass": ok})

    s = rep["samples"]
    check("min unique mapping, %", min(x["star"]["unique_pct"] for x in s), ">=", thr["min_unique_pct"])
    check("min assigned to genes, %", min(x["featurecounts"]["assigned_pct"] for x in s), ">=", thr["min_assigned_pct"])
    if rep["strandedness"]:  # an unstranded library has no "configured strand" to check
        check(
            "min share on the configured strand",
            min(x["strandedness"]["configured_share"] or 0 for x in s),
            ">=",
            thr["min_strand_share"],
        )
    check("strandedness inferred = configured", float(all(x["strandedness"]["matches"] for x in s)), ">=", 1.0)
    dr = [x["ercc_dose_response"] for x in s]
    check("min ERCC dose-response R2", min(d["r2"] for d in dr), ">=", thr["min_ercc_r2"])
    check("min ERCC slope", min(d["slope"] for d in dr), ">=", thr["min_ercc_slope"])
    check("max ERCC slope", max(d["slope"] for d in dr), "<=", thr["max_ercc_slope"])
    fold = rep["ercc_fold_change"]
    if fold:
        check("max |ERCC subgroup bias|, log2", fold["max_abs_subgroup_bias"], "<=", thr["max_ercc_bias_log2"])
    check("min replicate correlation", rep["replicates"]["min_within"], ">=", thr["min_replicate_pearson"])
    return out


# ----------------------------------------------------------------- вывод


def fnum(x, d=3):
    return "–" if x is None else ("%." + str(d) + "f") % x


def md_table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def render_md(rep):
    md = ["# RNA-seq: качество образцов и сверка с ERCC\n"]
    md.append(
        "Потоков: %s · featureCounts `-s %s` (%s) · фрагменты ERCC в линейной модели: ≥ %d\n"
        % (rep["threads"], rep["strandedness"], STRAND_NAMES[rep["strandedness"]], MIN_FIT_COUNT)
    )
    md.append("## Образцы\n")
    rows = []
    for s in rep["samples"]:
        rows.append(
            [
                s["sample"],
                s["ercc_mix"],
                s["fastp"]["pairs_before"],
                fnum(s["star"]["unique_pct"], 2),
                fnum(s["star"]["multi_pct"], 2),
                fnum(s["star"]["mismatch_pct"], 2),
                fnum(s["featurecounts"]["assigned_pct"], 1),
                fnum(100 * s["featurecounts"]["ercc_share"], 1),
                fnum(100 * s["strandedness"]["reverse_share"], 1),
                s["featurecounts"]["genes_detected_10"],
            ]
        )
    md.append(
        md_table(
            [
                "образец",
                "ERCC",
                "пары",
                "уникально, %",
                "мультикарт., %",
                "несовпадения, %",
                "в генах, %",
                "доля ERCC, %",
                "обратная цепь, %",
                "генов ≥ 10",
            ],
            rows,
        )
    )
    md.append("## Линейность по ERCC\n")
    rows = []
    for s in rep["samples"]:
        d = s["ercc_dose_response"]
        rows.append(
            [
                s["sample"],
                "%d / %d" % (d["detected"], d["ercc_total"]),
                d["fitted"],
                "%s [%s; %s]" % (fnum(d["slope"]), fnum(d["slope_ci"][0]), fnum(d["slope_ci"][1])),
                fnum(d["r2"]),
                fnum(d["dynamic_range_log10"], 1),
            ]
        )
    md.append(md_table(["образец", "найдено ERCC", "в модели", "наклон [95 % ДИ]", "R²", "диапазон, порядков"], rows))
    fold = rep["ercc_fold_change"]
    if fold:
        md.append("## Точность кратности по ERCC (%s / %s)\n" % (fold["numerator"], fold["denominator"]))
        md.append(
            "Сдвиг нормировки по подгруппе B: log2 = %s (×%s); ERCC в расчёте: %d; Пирсон с ожидаемым: %s; RMSE: %s.\n"
            % (
                fnum(fold["offset_log2"]),
                fnum(fold["offset_ratio"], 2),
                fold["n"],
                fnum(fold["pearson"]),
                fnum(fold["rmse"]),
            )
        )
        rows = [
            [
                g,
                v["n"],
                "%s (%s)" % (fnum(v["expected_ratio"], 2), fnum(v["expected_log2"])),
                fnum(v["median_adjusted"]),
                fnum(v["bias"]),
                fnum(v["rmse"]),
            ]
            for g, v in fold["subgroups"].items()
        ]
        md.append(md_table(["подгруппа", "n", "ожидается (log2)", "медиана log2", "смещение", "RMSE"], rows))
    md.append("## Реплики\n")
    r = rep["replicates"]
    md.append(
        "Генов с ≥ %d фрагментами в каждом образце: %d. Пирсон log2(CPM+1): "
        "внутри групп не ниже %s, между группами не выше %s.\n"
        % (MIN_FIT_COUNT, r["genes"], fnum(r["min_within"], 4), fnum(r["max_between"], 4))
    )
    if rep["markers"]:
        md.append("## Биология образцов: маркерные гены chr22\n")
        rows = []
        for m in rep["markers"]:
            if not m["found"]:
                rows.append([m["gene"], m["role"], m["expected_up"], "–", "–", "не найден"])
                continue
            rows.append(
                [
                    m["gene"],
                    m["role"],
                    m["expected_up"],
                    " / ".join(fnum(v, 1) for v in m["cpm"].values()),
                    fnum(m["log2fc"], 2),
                    "да" if m["agrees"] else "нет",
                ]
            )
        md.append(md_table(["ген", "роль", "ожидается выше", "CPM UHR / HBR", "log2FC", "совпало"], rows))
    if rep["checks"]:
        md.append("## Порог качества\n")
        md.append(
            md_table(
                ["проверка", "значение", "порог", "итог"],
                [
                    [c["name"], fnum(c["value"], 4), "%s %s" % (c["op"], c["limit"]), "✓" if c["pass"] else "✕"]
                    for c in rep["checks"]
                ],
            )
        )
    md.append("## Ресурсы\n")
    md.append(
        md_table(
            ["шаг", "время, с", "CPU, с", "пик памяти, МБ"],
            [
                [
                    s["step"],
                    fnum(s["wall_s"], 1),
                    fnum((s["user_s"] or 0) + (s["sys_s"] or 0), 1),
                    fnum(s["peak_rss_mb"], 0),
                ]
                for s in rep["steps"]
            ]
            + [
                [
                    "всего",
                    fnum(rep["totals"]["wall_s"], 1),
                    fnum(rep["totals"]["cpu_s"], 1),
                    fnum(rep["totals"]["max_peak_rss_mb"], 0),
                ]
            ],
        )
    )
    if rep["versions"]:
        md.append("## Версии\n")
        md.append(md_table(["программа", "версия"], rep["versions"]))
    return "\n".join(md)


def write_counts(path, fc, names, columns, col_of, samples):
    """Матрица счётов без строки с командой featureCounts: файл зависит только от данных."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\t".join(["gene_id", "gene_name", "gene_type", "length"] + list(samples)) + "\n")
        for g in sorted(fc):
            info = names.get(g, {})
            fh.write(
                "\t".join(
                    [g, info.get("name", g), info.get("type", ""), str(fc[g]["length"])]
                    + [str(fc[g]["counts"][col_of[s]]) for s in samples]
                )
                + "\n"
            )


def write_steps(path, steps):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("step\twall_s\tuser_s\tsys_s\tpeak_rss_mb\tthreads\texit_code\n")
        for s in steps:
            fh.write(
                "\t".join(
                    "" if s[k] is None else str(s[k])
                    for k in ("step", "wall_s", "user_s", "sys_s", "peak_rss_mb", "threads", "exit_code")
                )
            )
            fh.write("\n")


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--samples", nargs="+", required=True)
    p.add_argument("--groups", nargs="+", required=True)
    p.add_argument("--mixes", nargs="+", required=True)
    p.add_argument("--counts", required=True, help="featureCounts -o output")
    p.add_argument("--counts-summary", required=True)
    p.add_argument("--star-logs", nargs="+", required=True)
    p.add_argument("--star-gene-counts", nargs="+", required=True)
    p.add_argument("--fastp-json", nargs="+", required=True)
    p.add_argument("--ercc", required=True, help="ERCC concentration table (Thermo Fisher cms_095046)")
    p.add_argument("--annotation", help="GTF with gene_name and gene_type")
    p.add_argument("--strandedness", type=int, choices=(0, 1, 2), default=2)
    p.add_argument("--step-metrics", nargs="*", default=[])
    p.add_argument("--versions", nargs="*", default=[], help="TOOL_VERSIONS.tsv of the images")
    p.add_argument("--qc-thresholds")
    p.add_argument("--threads", type=int)
    p.add_argument("--out-prefix", default="rnaseq")
    return p.parse_args(argv)


def main(argv=None):
    a = parse_args(sys.argv[1:] if argv is None else argv)
    rep, fc, names, columns, col_of = build(a)
    with open(a.out_prefix + ".report.json", "w", encoding="utf-8") as fh:
        json.dump(rep, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    with open(a.out_prefix + ".report.md", "w", encoding="utf-8") as fh:
        fh.write(render_md(rep))
    write_counts(a.out_prefix + ".counts.tsv", fc, names, columns, col_of, a.samples)
    write_steps(a.out_prefix + ".step_metrics.tsv", rep["steps"])
    failed = [c["name"] for c in rep["checks"] if not c["pass"]]
    sys.stderr.write(
        "rnaseq_report: %d samples, %d checks, %d failed\n" % (len(rep["samples"]), len(rep["checks"]), len(failed))
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
