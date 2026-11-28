#!/usr/bin/env python3
"""Собирает evidence.json: каждое число из README и docs берётся отсюда.

    python3 scripts/build_evidence.py                  # тесты + эталонный прогон -> evidence.json
    python3 scripts/build_evidence.py --no-tests       # без запуска pytest (число тестов по --collect-only)
    python3 scripts/build_evidence.py --verify-source  # evidence.json собран из этих исходников?

Источники:
  docs/results/reference/HG002.report.json      эталонный прогон (scripts/run_pipeline.sh, 4 потока)
  docs/results/experiment_legacy_indels.report.json   тот же прогон с mpileup_profile=""
  docs/results/reproducibility_*.md              сравнения прогонов (scripts/check_reproducibility.sh)
  docs/results/build_tests.txt                   итоги make test htslib/samtools/bcftools при сборке
  docs/results/fastp_profile.txt                 профилирование fastp (docs/DEBUGGING.md, D-05)
  docs/DEBUGGING.md                              число случаев в журнале отладки
  docs/results/callers/compare.json              три вызывателя на одном BAM (scripts/compare_callers.py)
  docs/results/callers/reproducibility_*.md      воспроизводимость Strelka2 и DeepVariant при другом числе потоков
  docs/results/metrics/patent_metric.json        метрика патента RU 2846268 (scripts/concordance.py)
  docs/results/metrics/normalization_check.md    нормализация concordance.py против bcftools norm
  docs/results/rnaseq/rnaseq.report.json         RNA-seq: UHR/HBR против ERCC (scripts/rnaseq_report.py)
  docs/results/rnaseq/build_tests.txt            тесты featureCounts при сборке образа RNA-seq
  docs/results/rnaseq/reproducibility_*.md       воспроизводимость RNA-seq (scripts/check_rnaseq_reproducibility.sh)
  docs/results/fastp_isize_threads.md            длина вставки fastp при 1–4 потоках, релиз и патч (D-23)
  docs/results/depth/curve.json                  точность от глубины (scripts/depth_curve.py)
  docs/results/aggregation/representation.json   запись одних вариантов разными вызывателями (representation.py)
  docs/results/aggregation/callable.json         уверенный генотип по gVCF и AN в базе частот (callable_sites.py)
  docs/results/cram/cram.json                    BAM против CRAM: размер, время, потери (check_cram.sh)
  pytest                                         число и итог автотестов

--verify-source ловит evidence.json, который устарел относительно кода.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "docs", "results")
SOURCE_DIRS = ("bin", "scripts", "cwl", "config", "docker", "tests", "slurm")
SOURCE_FILES = ("Makefile", ".gitlab-ci.yml", "docs/results/reference/HG002.report.json")
# Когорта, для которой нижние оценки вычислений и хранения пересчитаны отдельно (docs/VACANCY.md):
# полногеномное секвенирование 120 тысяч человек для российской базы популяционных частот.
COHORT_120K = 120_000


def source_paths():
    """Files git tracks or would track: a fresh clone and a working copy hash the same.

    Ignored files (node_modules, caches) stay out (D-12). Untracked files that are not
    ignored are in: a source file created but not yet committed is hashed before the
    commit exactly as after it, so evidence.json built before `git add` stays valid (D-16)."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *SOURCE_DIRS, *SOURCE_FILES],
            cwd=ROOT,
            capture_output=True,
            check=True,
        ).stdout
        paths = {p for p in out.decode("utf-8").split("\0") if p and os.path.isfile(os.path.join(ROOT, p))}
        if paths:
            return sorted(paths)
    except (OSError, subprocess.CalledProcessError):
        pass
    paths = []  # no git (e.g. an unpacked archive without .git): walk, skipping what git would ignore
    for d in SOURCE_DIRS:
        for base, dirs, files in os.walk(os.path.join(ROOT, d)):
            dirs[:] = sorted(x for x in dirs if x not in ("__pycache__", "node_modules"))
            paths += [os.path.relpath(os.path.join(base, f), ROOT) for f in files if not f.endswith(".pyc")]
    return sorted(p.replace(os.sep, "/") for p in paths + list(SOURCE_FILES))


def source_hash():
    """sha256 over (path, bytes) of every source file; evidence.json and generated reports are not sources."""
    h = hashlib.sha256()
    for rel in source_paths():
        h.update(rel.encode() + b"\0")
        with open(os.path.join(ROOT, rel), "rb") as fh:
            h.update(fh.read() + b"\0")
    return h.hexdigest()


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def load(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        return json.load(fh)


def pytest_numbers(run):
    if not run:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-p", "no:cacheprovider"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        m = re.search(r"(\d+) tests? collected", out.stdout)
        return {"collected": int(m.group(1)) if m else None, "passed": None, "failed": None, "ran": False}
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    tail = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
    passed = re.search(r"(\d+) passed", tail)
    failed = re.search(r"(\d+) failed", tail)
    return {
        "collected": (int(passed.group(1)) if passed else 0) + (int(failed.group(1)) if failed else 0),
        "passed": int(passed.group(1)) if passed else 0,
        "failed": int(failed.group(1)) if failed else 0,
        "ran": True,
        "returncode": out.returncode,
        "summary": tail,
    }


def build_tests():
    """Итоги `make test` из docs/results/build_tests.txt, по порядку: htslib, samtools, bcftools."""
    text = read_text(os.path.join(RES, "build_tests.txt"))
    blocks = re.split(r"Number of tests:", text)[1:]
    out = {}
    for name, block in zip(("htslib", "samtools", "bcftools"), blocks):
        num = {k: int(v) for k, v in re.findall(r"(total|passed|failed|expected failure)\s+\.\.\s+(\d+)", block)}
        out[name] = num
    return out


def reproducibility():
    out = {}
    for fname in sorted(os.listdir(RES)):
        if not fname.startswith("reproducibility_") or not fname.endswith(".md"):
            continue
        rows = re.findall(
            r"^\| ([^|]+) \| `([0-9a-f]+)` \| `([0-9a-f]+)` \| (да|нет) \|$", read_text(os.path.join(RES, fname)), re.M
        )
        out[fname[len("reproducibility_") : -3]] = {r[0].strip(): r[3] == "да" for r in rows}
    return out


def fmt(x, d=4):
    return ("%." + str(d) + "f") % x


def fmt_ci(c, d=3):
    return "%s–%s" % (fmt(c[0], d), fmt(c[1], d))


def fmt_p(p):
    return "%.2g" % p if p < 0.001 else "%.3f" % p


CALLER_TAGS = (("strelka2", "strelka2"), ("deepvariant", "dv"), ("bcftools", "bcftools"))
TRUTH_TAGS = (("giab_v5.0q", "v5"), ("giab_v4.2.1", "v421"))


def callers_claims():
    """Ключи сравнения вызывателей, воспроизводимости и метрики патента."""
    claims = {}
    cmp_ = load("docs/results/callers/compare.json")
    for truth, ttag in TRUTH_TAGS:
        for caller, ctag in CALLER_TAGS:
            for vtype in ("SNP", "INDEL"):
                r = cmp_["benchmark"][truth][caller][vtype]
                k = "%s_%s_%s" % (ctag, vtype.lower(), ttag)
                claims[k + "_f1"] = fmt(r["f1"])
                claims[k + "_f1_ci"] = fmt_ci(r["f1_ci"])
                claims[k + "_recall"] = fmt(r["recall"])
                claims[k + "_precision"] = fmt(r["precision"])
                claims[k + "_fn"] = str(r["fn"])
                claims[k + "_fp"] = str(r["fp"])
        for other, mc in cmp_["mcnemar"][truth].items():
            otag = dict(CALLER_TAGS)[other]
            for vtype in ("SNP", "INDEL"):
                e = mc[vtype]
                k = "mcnemar_%s_%s_%s_%s" % (vtype.lower(), ttag, dict(CALLER_TAGS)[cmp_["base"]], otag)
                claims[k + "_only_base"] = str(e["only_base"])
                claims[k + "_only_other"] = str(e["only_other"])
                claims[k + "_p"] = fmt_p(e["p"])
    for caller, ctag in CALLER_TAGS:
        for subset, stag in (("tandem_repeats", "tr"), ("all_difficult", "difficult"), ("homopolymers_ge7", "hp")):
            for vtype in ("SNP", "INDEL"):
                r = cmp_["strata"]["giab_v5.0q"][caller][subset][vtype]
                claims["%s_%s_v5_%s_f1" % (ctag, vtype.lower(), stag)] = fmt(r["f1"], 3)
        res = cmp_["resources"][caller]
        claims[ctag + "_call_wall_s"] = fmt(res["wall_s"], 0)
        claims[ctag + "_call_cpu_s"] = fmt(res["cpu_s"], 0)
        claims[ctag + "_call_peak_mb"] = fmt(res["peak_rss_mb"], 0)
    claims["dv_vs_strelka2_cpu_x"] = fmt(
        cmp_["resources"]["deepvariant"]["cpu_s"] / cmp_["resources"]["strelka2"]["cpu_s"], 1
    )

    for name, tag in (("strelka2_threads", "strelka2"), ("deepvariant_threads", "dv")):
        text = read_text(os.path.join(RES, "callers", "reproducibility_%s.md" % name))
        rows = dict(re.findall(r"^\| ([^|]+?) \| `[0-9a-f]+` \| `[0-9a-f]+` \| (да|нет) \|$", text, re.M))
        claims[tag + "_repro_vcf"] = rows["VCF, байты (sha256)"]
        claims[tag + "_repro_gvcf"] = rows["gVCF, байты (sha256)"]

    pm = load("docs/results/metrics/patent_metric.json")["results"]
    for truth, ttag in TRUTH_TAGS:
        for caller, ctag in CALLER_TAGS:
            e = pm[truth][caller]
            claims["patent_f_%s_%s" % (ttag, ctag)] = fmt(100 * e["literal"]["f"], 2)
            claims["patent_f_norm_%s_%s" % (ttag, ctag)] = fmt(100 * e["normalized"]["f"], 2)
            claims["patent_den_share_%s_%s" % (ttag, ctag)] = fmt(
                100 * e["normalized"]["truth_in_denominator_share"], 1
            )
            claims["patent_lit_den_%s_%s" % (ttag, ctag)] = str(e["literal"]["denominator"])
            claims["patent_norm_den_%s_%s" % (ttag, ctag)] = str(e["normalized"]["denominator"])
            for subset, stag in (("not_in_all_difficult", "easy"), ("all_difficult", "difficult")):
                claims["patent_f_%s_%s_%s" % (ttag, ctag, stag)] = fmt(100 * e["strata"][subset]["f"], 2)
    for truth, ttag in TRUTH_TAGS:
        claims["patent_truth_multi_" + ttag] = str(pm[truth]["strelka2"]["literal"]["truth_multiallelic"])
    shift_gain = sum(
        pm[t][c]["normalized"]["denominator"] - pm[t][c]["split_only"]["denominator"]
        for t, _ in TRUTH_TAGS
        for c, _ in CALLER_TAGS
    )
    claims["patent_left_shift_gain"] = str(shift_gain)
    claims["patent_pass_v421"] = str(sum(1 for c, _ in CALLER_TAGS if pm["giab_v4.2.1"][c]["literal"]["f"] > 0.999))
    claims["patent_pass_v5"] = str(sum(1 for c, _ in CALLER_TAGS if pm["giab_v5.0q"][c]["literal"]["f"] > 0.999))

    norm = read_text(os.path.join(RES, "metrics", "normalization_check.md"))
    m = re.search(r"Итог: (\d+) записей, расхождений (\d+)", norm)
    claims["norm_check_records"], claims["norm_check_diff"] = m.group(1), m.group(2)
    return claims


def rnaseq_claims():
    """Ключи RNA-seq: качество образцов, линейность и кратность по ERCC, реплики, ресурсы, тесты сборки."""
    rep = load("docs/results/rnaseq/rnaseq.report.json")
    s = rep["samples"]
    claims = {"rnaseq_samples": str(len(s))}

    def span(key, values, d):
        claims[key + "_min"], claims[key + "_max"] = fmt(min(values), d), fmt(max(values), d)

    span("rnaseq_pairs", [x["fastp"]["pairs_before"] for x in s], 0)
    span("rnaseq_unique_pct", [x["star"]["unique_pct"] for x in s], 1)
    span("rnaseq_assigned_pct", [x["featurecounts"]["assigned_pct"] for x in s], 1)
    span("rnaseq_strand_pct", [100 * x["strandedness"]["reverse_share"] for x in s], 1)
    span("rnaseq_genes_detected", [x["featurecounts"]["genes_detected_10"] for x in s], 0)
    span("rnaseq_splices_annotated_pct", [100.0 * x["star"]["splices_annotated"] / x["star"]["splices"] for x in s], 1)
    for group in ("UHR", "HBR"):
        g = [x for x in s if x["group"] == group]
        claims["rnaseq_ercc_share_%s" % group.lower()] = fmt(
            100 * sum(x["featurecounts"]["ercc_share"] for x in g) / len(g), 0
        )
        lod = rep["groups"][group]["detection_limit"]
        claims["rnaseq_lod_%s" % group.lower()] = ("%.3g" % lod).rstrip("0").rstrip(".") if lod else "–"
    dr = [x["ercc_dose_response"] for x in s]
    span("rnaseq_slope", [d["slope"] for d in dr], 2)
    span("rnaseq_r2", [d["r2"] for d in dr], 3)
    span("rnaseq_ercc_detected", [d["detected"] for d in dr], 0)
    span("rnaseq_ercc_fitted", [d["fitted"] for d in dr], 0)
    span("rnaseq_dynamic_range", [d["dynamic_range_log10"] for d in dr], 1)
    claims["rnaseq_slope_ci_lo_min"] = fmt(min(d["slope_ci"][0] for d in dr), 2)
    claims["rnaseq_slope_ci_hi_max"] = fmt(max(d["slope_ci"][1] for d in dr), 2)
    claims["rnaseq_slope_ci_cover_1"] = str(sum(1 for d in dr if d["slope_ci"][0] <= 1 <= d["slope_ci"][1]))

    fold = rep["ercc_fold_change"]
    claims.update(
        {
            "rnaseq_fc_n": str(fold["n"]),
            "rnaseq_fc_offset": fmt(fold["offset_ratio"], 2),
            "rnaseq_fc_offset_log2": fmt(fold["offset_log2"], 2),
            "rnaseq_fc_pearson": fmt(fold["pearson"], 3),
            "rnaseq_fc_rmse": fmt(fold["rmse"], 2),
            "rnaseq_fc_max_bias": fmt(fold["max_abs_subgroup_bias"], 2),
        }
    )
    for g, v in fold["subgroups"].items():
        claims["rnaseq_fc_n_%s" % g] = str(v["n"])
        claims["rnaseq_fc_median_%s" % g] = fmt(v["median_adjusted"], 2)
        claims["rnaseq_fc_expected_%s" % g] = fmt(v["expected_log2"], 2)
        claims["rnaseq_fc_bias_%s" % g] = "%+.2f" % v["bias"]
        claims["rnaseq_fc_rmse_%s" % g] = fmt(v["rmse"], 2)
        claims["rnaseq_fc_ratio_%s" % g] = fmt(2 ** v["median_adjusted"], 2)

    r = rep["replicates"]
    claims["rnaseq_rep_genes"] = str(r["genes"])
    claims["rnaseq_rep_within_min"] = fmt(r["min_within"], 3)
    claims["rnaseq_rep_between_max"] = fmt(r["max_between"], 3)
    found = [m for m in rep["markers"] if m["found"]]
    claims["rnaseq_markers"] = "%d/%d" % (sum(1 for m in found if m["agrees"]), len(rep["markers"]))
    for m in found:
        claims["rnaseq_marker_%s_lfc" % m["gene"].lower()] = fmt(m["log2fc"], 1)

    agree = [x["counter_agreement"] for x in s]
    claims["rnaseq_counter_diff_max"] = fmt(max(abs(a["total_diff_pct"]) for a in agree), 1)
    claims["rnaseq_counter_r_min"] = fmt(min(a["pearson_log2"] for a in agree), 3)
    claims["rnaseq_counter_ercc_identical"] = "да" if all(a["ercc_identical"] for a in agree) else "нет"

    steps = {st["step"]: st for st in rep["steps"]}
    align = [st for name, st in steps.items() if name.startswith("star_align_")]
    claims.update(
        {
            "rnaseq_index_wall_s": fmt(steps["star_index"]["wall_s"], 0),
            "rnaseq_index_peak_gb": fmt(steps["star_index"]["peak_rss_mb"] / 1024.0, 1),
            "rnaseq_align_wall_max_s": fmt(max(st["wall_s"] for st in align), 1),
            "rnaseq_align_peak_gb_max": fmt(max(st["peak_rss_mb"] for st in align) / 1024.0, 1),
            "rnaseq_total_wall_s": fmt(rep["totals"]["wall_s"], 0),
            "rnaseq_total_cpu_s": fmt(rep["totals"]["cpu_s"], 0),
            "rnaseq_qc_checks": "%d/%d" % (sum(c["pass"] for c in rep["checks"]), len(rep["checks"])),
        }
    )

    text = read_text(os.path.join(RES, "rnaseq", "build_tests.txt"))
    m = re.search(r"featureCounts tests: passed (\d+), failed (\d+)", text)
    claims["featurecounts_tests_passed"], claims["featurecounts_tests_failed"] = m.group(1), m.group(2)

    for fname in sorted(os.listdir(os.path.join(RES, "rnaseq"))):
        if not (fname.startswith("reproducibility_") and fname.endswith(".md")):
            continue
        rows = dict(
            re.findall(
                r"^\| ([^|]+?) \| `[0-9a-f]+` \| `[0-9a-f]+` \| (да|нет) \|$",
                read_text(os.path.join(RES, "rnaseq", fname)),
                re.M,
            )
        )
        tag = "rnaseq_repro_" + fname[len("reproducibility_") : -3]
        claims[tag + "_counts"] = rows["матрица счётов (counts.tsv)"]
        claims[tag + "_bam_records"] = rows["BAM, выравнивания"]
        claims[tag + "_bam_bytes"] = rows["BAM, байты (sha256)"]
        claims[tag + "_report"] = rows["числа отчёта"]
    return claims


def fastp_isize_rows(text):
    """Таблицы docs/results/fastp_isize_threads.md: {(набор, сборка, потоков): строка}."""
    rows, dataset = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            dataset = line[3:].strip()
            continue
        m = re.match(
            r"^\| (official|release|patched) \| (\d+) \| (\d+) \| (\d+) \| (\d+) \| `([0-9a-f]+)` \| `([0-9a-f]+)` \|$",
            line,
        )
        if m and dataset:
            rows[(dataset, m.group(1), int(m.group(2)))] = {
                "pairs": int(m.group(3)),
                "evaluated": int(m.group(4)),
                "peak": int(m.group(5)),
                "hist": m.group(6),
                "reads": m.group(7),
            }
    return rows


def fastp_isize_claims():
    rows = fastp_isize_rows(read_text(os.path.join(RES, "fastp_isize_threads.md")))
    claims = {}
    threads = sorted({t for _, _, t in rows})
    for dataset, tag in (("RNA-seq UHR_Rep1", "rna"), ("WGS HG002", "wgs")):
        for t in threads:
            r = rows[(dataset, "official", t)]
            claims["fastp_isize_%s_evaluated_t%d" % (tag, t)] = str(r["evaluated"])
            claims["fastp_isize_%s_peak_t%d" % (tag, t)] = str(r["peak"])
            claims["fastp_isize_%s_share_t%d" % (tag, t)] = fmt(
                100.0 * r["evaluated"] / rows[(dataset, "official", 1)]["evaluated"], 0
            )
        claims["fastp_isize_%s_patched_peak" % tag] = str(rows[(dataset, "patched", threads[-1])]["peak"])
    same = lambda pred: "да" if all(pred(k, v) for k, v in rows.items()) else "нет"  # noqa: E731
    claims["fastp_isize_release_matches_official"] = same(
        lambda k, v: k[1] != "release" or v["hist"] == rows[(k[0], "official", k[2])]["hist"]
    )
    claims["fastp_isize_patched_thread_independent"] = same(
        lambda k, v: k[1] != "patched" or v["hist"] == rows[(k[0], "official", 1)]["hist"]
    )
    claims["fastp_isize_reads_identical"] = same(lambda k, v: v["reads"] == rows[(k[0], "official", 1)]["reads"])
    claims["fastp_isize_threads_max"] = str(threads[-1])
    return claims


def depth_tag(fraction):
    return "f%d" % int(round(fraction * 1000))


def depth_claims():
    """Ключи кривой глубины: F1 (v5.0q), F патента и доля эталона в знаменателе (v4.2.1), повторы."""
    res = load("docs/results/depth/curve.json")
    claims = {}
    seed1 = [p for p in res["points"] if p["seed"] == 1]
    claims["depth_points"] = str(len(seed1))
    claims["depth_min_x"] = fmt(min(p["mean_depth"] for p in seed1), 1)
    claims["depth_max_x"] = fmt(max(p["mean_depth"] for p in seed1), 1)
    for p in seed1:
        tag = depth_tag(p["fraction"])
        claims["depth_%s_x" % tag] = fmt(p["mean_depth"], 1)
        for caller, ctag in CALLER_TAGS:
            if caller not in p["callers"]:
                continue
            e = p["callers"][caller]
            for vtype in ("SNP", "INDEL"):
                claims["depth_%s_%s_%s_f1" % (tag, ctag, vtype.lower())] = fmt(e["giab_v5.0q"][vtype]["f1"], 3)
            for truth, ttag in TRUTH_TAGS:
                pat = e[truth]["patent"]
                claims["depth_%s_%s_f_%s" % (tag, ctag, ttag)] = fmt(100 * pat["f"], 2)
                claims["depth_%s_%s_share_%s" % (tag, ctag, ttag)] = fmt(100 * pat["truth_in_denominator_share"], 1)
                claims["depth_%s_%s_den_%s" % (tag, ctag, ttag)] = str(pat["denominator"])
                claims["depth_%s_%s_err_%s" % (tag, ctag, ttag)] = str(pat["denominator"] - pat["numerator"])
    for truth, ttag in TRUTH_TAGS:
        for caller, ctag in CALLER_TAGS:
            passing = [p for p in seed1 if caller in p["callers"] and p["callers"][caller][truth]["patent"]["pass"]]
            claims["depth_pass_%s_%s" % (ttag, ctag)] = str(len(passing))
    for frac, e in res["replicates"].items():
        tag = depth_tag(float(frac))
        claims["depth_rep_%s_seeds" % tag] = str(len(e["seeds"]))
        claims["depth_rep_%s_x" % tag] = "%s–%s" % (fmt(e["depths"][0], 1), fmt(e["depths"][-1], 1))
        for caller, ctag in CALLER_TAGS:
            for vtype in ("SNP", "INDEL"):
                k = "%s giab_v5.0q %s F1" % (caller, vtype)
                if k in e:
                    lo, hi = e[k]
                    claims["depth_rep_%s_%s_%s_f1" % (tag, ctag, vtype.lower())] = "%s–%s" % (fmt(lo, 3), fmt(hi, 3))
            for truth, ttag in TRUTH_TAGS:
                k = "%s %s F" % (caller, truth)
                if k in e:
                    lo, hi = e[k]
                    claims["depth_rep_%s_%s_f_%s" % (tag, ctag, ttag)] = "%s–%s" % (fmt(100 * lo, 2), fmt(100 * hi, 2))
                    claims["depth_rep_%s_%s_f_%s_span" % (tag, ctag, ttag)] = fmt(100 * (hi - lo), 2)
    return claims


def aggregation_claims():
    """Ключи для базы частот: запись вариантов разными вызывателями, уверенные позиции gVCF, AN."""
    rep = load("docs/results/aggregation/representation.json")
    tags = dict(CALLER_TAGS)
    claims = {"repr_union_raw": str(rep["union"]["raw"]), "repr_union_norm": str(rep["union"]["norm"])}
    shares, split_shares, kinds = [], [], {}
    for p in rep["pairs"]:
        tag = "repr_%s_%s" % (tags[p["a"]], tags[p["b"]])
        d = p["breakdown"]
        claims[tag + "_raw"] = str(d["raw_discordant"])
        claims[tag + "_split"] = str(d["removed_by_split"])
        claims[tag + "_shift"] = str(d["removed_by_left_shift"])
        claims[tag + "_same"] = str(d["same_haplotype"])
        claims[tag + "_loci"] = str(p["same_haplotype_loci"])
        claims[tag + "_real"] = str(d["real"])
        claims[tag + "_share"] = fmt(100 * d["representation_share"], 0)
        claims[tag + "_split_share"] = fmt(100 * d["removed_by_split"] / float(d["raw_discordant"]), 0)
        claims[tag + "_gt"] = str(p["gt_differs"])
        shares.append(d["representation_share"])
        split_shares.append(d["removed_by_split"] / float(d["raw_discordant"]))
        for k, n in p["kinds"].items():
            kinds[k] = kinds.get(k, 0) + n
    claims["repr_share_min"], claims["repr_share_max"] = fmt(100 * min(shares), 0), fmt(100 * max(shares), 0)
    claims["repr_split_share_min"] = fmt(100 * min(split_shares), 0)
    claims["repr_split_share_max"] = fmt(100 * max(split_shares), 0)
    claims["repr_shift_total"] = str(sum(p["breakdown"]["removed_by_left_shift"] for p in rep["pairs"]))
    claims["repr_loci_total"] = str(sum(p["same_haplotype_loci"] for p in rep["pairs"]))
    claims["repr_loci_verified"] = str(sum(p["same_haplotype_loci_verified"] for p in rep["pairs"]))
    claims["repr_kind_subs_vs_indels"] = str(kinds.get("замены против инделов", 0))
    claims["repr_loci_distinct"] = str(len(rep["loci"]))
    claims["repr_loci_difficult"] = str(sum(1 for x in rep["loci"] if x.get("in_difficult")))
    claims["repr_kind_indels"] = str(kinds.get("инделы разложены по-разному", 0))
    cal = load("docs/results/aggregation/callable.json")
    claims["callable_gq_min"] = str(cal["gq_min"])
    for p in cal["points"]:
        tag = "f%d" % int(round(1000 * float(re.match(r"f([0-9.]+)_", p["label"]).group(1))))
        claims["callable_%s_x" % tag] = fmt(p["mean_depth"], 1)
        claims["callable_%s_bases" % tag] = fmt(100 * p["bases_confident"], 1)
        claims["callable_%s_difficult" % tag] = fmt(100 * p["bases_confident_all_difficult"], 1)
        claims["callable_%s_easy" % tag] = fmt(100 * p["bases_confident_not_in_all_difficult"], 1)
        claims["callable_%s_truth" % tag] = fmt(100 * p["truth_sites_confident"], 1)
        claims["callable_%s_truth_sites" % tag] = str(p["truth_sites"])
        claims["callable_%s_truth_low" % tag] = str(p["truth_sites_low"])
        claims["callable_%s_truth_low_difficult" % tag] = str(p["truth_sites_low_difficult"])
        claims["callable_%s_truth_difficult" % tag] = str(p["truth_sites_difficult"])
    for name, c in cal["cohorts"].items():
        tag = "cohort_%s" % name
        claims[tag + "_samples"] = str(c["samples"])
        claims[tag + "_x"] = "%s–%s" % (fmt(min(c["depths"]), 1), fmt(max(c["depths"]), 1))
        claims[tag + "_no_known"] = str(c["sites_without_known"])
        for g in ("het", "hom"):
            e = c[g]
            claims["%s_%s_sites" % (tag, g)] = str(e["sites"])
            claims["%s_%s_naive" % (tag, g)] = fmt(e["naive_af_mean"], 3)
            claims["%s_%s_honest" % (tag, g)] = fmt(e["honest_af_mean"], 3)
            claims["%s_%s_unknown" % (tag, g)] = fmt(100 * e["unknown_share_mean"], 1)
            claims["%s_%s_naive_off" % (tag, g)] = fmt(100 * e["naive_off_by_0_1"], 1)
            claims["%s_%s_honest_off" % (tag, g)] = fmt(100 * e["honest_off_by_0_1"], 1)
    return claims


def cram_claims():
    """Ключи сравнения BAM и CRAM: размер, доля от BAM, время, проверки без потерь, оценка для когорты."""
    res = load("docs/results/cram/cram.json")
    tags = {"BAM": "bam", "CRAM 3.0": "v30", "CRAM 3.1": "v31", "CRAM 3.1 archive": "v31a"}
    claims = {"cram_cohort": "{:,}".format(res["assumptions"]["cohort"]).replace(",", " ")}
    f = {tags[x["format"]]: x for x in res["formats"]}
    for tag, x in f.items():
        claims["cram_%s_mb" % tag] = fmt(x["bytes"] / 1e6, 1)
        claims["cram_%s_share" % tag] = fmt(100 * x["share_of_bam"], 0)
        claims["cram_%s_read_s" % tag] = fmt(x["read_s"], 2)
        claims["cram_%s_genome_gb" % tag] = fmt(x["genome_gb"], 0)
        claims["cram_%s_cohort_pb" % tag] = fmt(x["cohort_pb"], 1)
        if x["write_s"] is not None:
            claims["cram_%s_write_s" % tag] = fmt(x["write_s"], 1)
    crams = [x for t, x in f.items() if t != "bam"]
    claims["cram_records_identical"] = "да" if all(x["records_identical"] == "yes" for x in crams) else "нет"
    claims["cram_calls_identical"] = "да" if all(x["calls_identical"] == "yes" for x in crams) else "нет"
    claims["cram_sam_bytes_identical"] = "да" if all(x["sam_bytes_identical"] == "yes" for x in crams) else "нет"
    claims["cram_v31_vs_v30"] = fmt(100 * (1 - f["v31"]["bytes"] / f["v30"]["bytes"]), 0)
    claims["cram_v31_read_x"] = fmt(f["v31"]["read_s"] / f["bam"]["read_s"], 1)
    claims["cram_v31a_write_x"] = fmt(f["v31a"]["write_s"] / f["v31"]["write_s"], 0)
    claims["cram_saving_v31_pb"] = fmt(f["bam"]["cohort_pb"] - f["v31"]["cohort_pb"], 1)
    return claims


def cohort_claims(ref, cram_formats, cohort=COHORT_120K):
    """Нижние оценки для когорты геномов 30x: CPU-часы и объём BAM и CRAM 3.1.

    Тот же линейный пересчёт с участка на геном, что у оценок для 100 000 геномов в отчёте прогона
    (scaling) и в таблице CRAM (cram_report.py): меняется только число геномов."""
    per_genome_cpu_h = ref["scaling"]["cpu_hours_per_30x_genome_lower_bound"]
    f = {x["format"]: x for x in cram_formats}
    bam, v31 = f["BAM"]["genome_gb"], f["CRAM 3.1"]["genome_gb"]
    return {
        "cohort_120k": "{:,}".format(cohort).replace(",", " "),
        "cpu_mh_120k_lb": fmt(per_genome_cpu_h * cohort / 1e6, 1),
        "cram_bam_120k_pb": fmt(bam * cohort / 1e6, 1),
        "cram_v31_120k_pb": fmt(v31 * cohort / 1e6, 1),
        "cram_saving_v31_120k_pb": fmt((bam - v31) * cohort / 1e6, 1),
    }


def build(run_tests):
    ref = load("docs/results/reference/HG002.report.json")
    legacy = load("docs/results/experiment_legacy_indels.report.json")

    def row(rep, truth, vtype):
        return next(r for r in rep["benchmark"][truth]["summary"] if r["type"] == vtype and r["filter"] == "PASS")

    claims = {}
    for truth, tag in (("giab_v5.0q", "v5"), ("giab_v4.2.1", "v421")):
        for vtype in ("SNP", "INDEL"):
            r = row(ref, truth, vtype)
            k = "%s_%s" % (vtype.lower(), tag)
            claims[k + "_f1"] = fmt(r["f1"])
            claims[k + "_f1_ci"] = "%s–%s" % (fmt(r["f1_ci"][0], 3), fmt(r["f1_ci"][1], 3))
            claims[k + "_recall"] = fmt(r["recall"])
            claims[k + "_precision"] = fmt(r["precision"])
            claims[k + "_fp"] = str(r["fp"])
            claims[k + "_fn"] = str(r["fn"])
            claims[k + "_truth"] = str(r["truth_total"])
            lg = row(legacy, truth, vtype)
            claims[k + "_f1_legacy"] = fmt(lg["f1"])
            claims[k + "_f1_legacy_ci"] = "%s–%s" % (fmt(lg["f1_ci"][0], 3), fmt(lg["f1_ci"][1], 3))

    def stratum(truth, vtype, subset):
        return next(r for r in ref["benchmark"][truth]["strata"] if r["type"] == vtype and r["subset"] == subset)

    for subset, tag in (
        ("not_in_all_difficult", "easy"),
        ("all_difficult", "difficult"),
        ("tandem_repeats", "tr"),
        ("homopolymers_ge7", "hp"),
    ):
        for vtype in ("SNP", "INDEL"):
            claims["%s_v5_%s_f1" % (vtype.lower(), tag)] = fmt(stratum("giab_v5.0q", vtype, subset)["f1"], 3)
    claims["oxog_fisher_p"] = fmt(ref["benchmark"]["giab_v5.0q"]["oxog"]["fisher_p"], 2)
    claims["fp_snv_v5"] = str(ref["benchmark"]["giab_v5.0q"]["oxog"]["fp_total"])

    steps = {s["step"]: s for s in ref["steps"]}
    aln, calls, reads = ref["alignment"], ref["calls"], ref["reads"]
    claims.update(
        {
            "read_pairs": str(reads["pairs_before"]),
            "mean_depth": fmt(aln["mean_depth"], 1),
            "dup_rate_pct": fmt(100 * aln["dup_rate"], 1),
            "optical_dup_pct": fmt(100 * aln["optical_dup_rate"], 1),
            "library_dup_pct": fmt(100 * aln["library_dup_rate"], 1),
            "ts_tv": fmt(calls["ts_tv"], 2),
            "dispersion_index": fmt(aln["depth"]["dispersion_index"], 2),
            "total_wall_s": fmt(ref["totals"]["wall_s"], 0),
            "total_cpu_s": fmt(ref["totals"]["cpu_s"], 0),
            "max_peak_rss_mb": fmt(ref["totals"]["max_peak_rss_mb"], 0),
            "fastp_wall_s": fmt(steps["fastp"]["wall_s"], 1),
            "bwa_wall_s": fmt(steps["bwa_mem2_mem"]["wall_s"], 1),
            "cpu_h_per_genome_lb": fmt(ref["scaling"]["cpu_hours_per_30x_genome_lower_bound"], 0),
            "cpu_mh_100k_lb": fmt(ref["scaling"]["cpu_hours_100k_genomes_lower_bound"] / 1e6, 1),
            "qc_checks": "%d/%d" % (sum(c["pass"] for c in ref["checks"]), len(ref["checks"])),
        }
    )
    fastp = dict(
        re.findall(
            r"^(default flags|plain input, WITHOUT --detect_adapter_for_pe)\S*.*?(\d+\.\d)$",
            read_text(os.path.join(RES, "fastp_profile.txt")),
            re.M,
        )
    )
    claims["fastp_before_s"] = fastp.get("default flags")
    claims["fastp_after_s"] = fastp.get("plain input, WITHOUT --detect_adapter_for_pe")

    bt = build_tests()
    for name, num in bt.items():
        claims["%s_tests_passed" % name] = str(num.get("passed"))
        claims["%s_tests_failed" % name] = str(num.get("failed"))
        claims["%s_tests_total" % name] = str(num.get("total"))

    rep = reproducibility()
    vcf_identical = all(v.get("VCF, байты (sha256)") for v in rep.values())
    claims["repro_comparisons"] = str(len(rep))
    claims["repro_vcf_identical"] = "да" if vcf_identical else "нет"

    claims["debug_cases"] = str(
        len(re.findall(r"^## D-\d+", read_text(os.path.join(ROOT, "docs", "DEBUGGING.md")), re.M))
    )

    claims.update(callers_claims())
    claims.update(rnaseq_claims())
    claims.update(fastp_isize_claims())
    claims.update(depth_claims())
    claims.update(aggregation_claims())
    claims.update(cram_claims())
    claims.update(cohort_claims(ref, load("docs/results/cram/cram.json")["formats"]))

    tests = pytest_numbers(run_tests)
    claims["unit_tests"] = str(tests["collected"])
    cwl_tools = sorted(f for f in os.listdir(os.path.join(ROOT, "cwl", "tools")) if f.endswith(".cwl"))
    claims["cwl_tools"] = str(len(cwl_tools))

    return {
        "_doc": "Generated by scripts/build_evidence.py. Do not edit by hand.",
        "source_sha256": source_hash(),
        "claims": claims,
        "tests": tests,
        "build_tests": bt,
        "reproducibility": rep,
        "cwl_tools": cwl_tools,
        "versions": ref["versions"],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--no-tests", action="store_true", help="do not run pytest")
    p.add_argument("--verify-source", action="store_true", help="only check evidence.json is up to date")
    a = p.parse_args(argv)
    path = os.path.join(ROOT, "evidence.json")
    if a.verify_source:
        with open(path, encoding="utf-8") as fh:
            stored = json.load(fh)
        now = source_hash()
        if stored.get("source_sha256") != now:
            sys.stderr.write(
                "evidence.json is stale: sources changed since it was built.\n"
                "  stored %s\n  now    %s\nrun: python3 scripts/build_evidence.py\n"
                % (stored.get("source_sha256"), now)
            )
            return 1
        print("evidence.json matches the sources (%s)" % now[:16])
        return 0
    ev = build(run_tests=not a.no_tests)
    if ev["tests"].get("ran") and (ev["tests"].get("returncode") or ev["tests"].get("failed")):
        sys.stderr.write("pytest is red (%s): evidence not written\n" % ev["tests"].get("summary"))
        return 1
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(ev, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    print("evidence.json: %d claims, source %s" % (len(ev["claims"]), ev["source_sha256"][:16]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
