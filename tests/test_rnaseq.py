"""rnaseq_report.py on synthetic inputs and policy checks of the RNA-seq CWL (no containers)."""

import json
import math
import os

import pytest
from ruamel.yaml import YAML

import rnaseq_report as rr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
yaml = YAML(typ="safe")

ERCC_HEADER = (
    "Re-sort ID\tERCC ID\tsubgroup\tconcentration in Mix 1 (attomoles/ul)\t"
    "concentration in Mix 2 (attomoles/ul)\texpected fold-change ratio\tlog2(Mix 1/Mix 2)\n"
)
# subgroup -> Mix1/Mix2 ratio, as in the Thermo Fisher table
RATIOS = {"A": 4.0, "B": 1.0, "C": 2 / 3.0, "D": 0.5}


def ercc_rows(levels=(30000.0, 7500.0, 1875.0, 468.75, 117.19, 29.3)):
    """Two ERCC per subgroup and concentration level: (id, subgroup, mix1, mix2)."""
    rows, n = [], 0
    for g, ratio in RATIOS.items():
        for c in levels:
            for _ in range(2):
                n += 1
                rows.append(("ERCC-%05d" % n, g, c, c / ratio))
    return rows


def write_ercc_table(path, rows):
    with open(path, "w") as fh:
        fh.write(ERCC_HEADER)
        for i, (e, g, m1, m2) in enumerate(rows, 1):
            fh.write("%d\t%s\t%s\t%s\t%s\t%.2f\t%.2f\n" % (i, e, g, m1, m2, m1 / m2, math.log2(m1 / m2)))


# ----------------------------------------------------------------- parsers


def test_ercc_table_ratio_comes_from_concentrations(tmp_path):
    p = tmp_path / "ercc.tsv"
    write_ercc_table(p, ercc_rows())
    t = rr.read_ercc_table(str(p))
    assert len(t) == 48
    c = next(v for v in t.values() if v["subgroup"] == "C")
    # the table rounds log2(2/3) to -0.58; the report uses the exact value
    assert abs(c["log2_ratio"] - math.log2(2 / 3.0)) < 1e-12


def test_star_log_and_gene_counts_are_parsed(tmp_path):
    log = tmp_path / "S.Log.final.out"
    log.write_text(
        "                          Number of input reads |\t1000\n"
        "                   Uniquely mapped reads number |\t950\n"
        "                        Uniquely mapped reads % |\t95.00%\n"
        "             % of reads mapped to multiple loci |\t3.10%\n"
        "                      Mismatch rate per base, % |\t0.14%\n"
        "                       Number of splices: Total |\t400\n"
        "            Number of splices: Annotated (sjdb) |\t390\n"
    )
    s = rr.read_star_log(str(log))
    assert s["input_pairs"] == 1000 and s["unique"] == 950
    assert s["unique_pct"] == 95.0 and s["multi_pct"] == 3.1 and s["mismatch_pct"] == 0.14
    assert s["splices_annotated"] == 390
    tab = tmp_path / "S.ReadsPerGene.out.tab"
    tab.write_text("N_unmapped\t5\t5\t5\nN_noFeature\t9\t90\t8\nG1\t10\t1\t9\nERCC-00001\t7\t0\t7\n")
    special, genes = rr.read_star_gene_counts(str(tab))
    assert special["N_noFeature"] == (9, 90, 8)
    assert genes == {"G1": (10, 1, 9), "ERCC-00001": (7, 0, 7)}


def test_featurecounts_table_and_summary(tmp_path):
    fc = tmp_path / "featureCounts.txt"
    fc.write_text(
        '# Program:featureCounts v2.1.1; Command:"featureCounts" "-T" "4"\n'
        "Geneid\tChr\tStart\tEnd\tStrand\tLength\tA.Aligned.sortedByCoord.out.bam\tB.Aligned.sortedByCoord.out.bam\n"
        "G1\tchr22\t1\t100\t+\t100\t5\t7\n"
    )
    cols, genes = rr.read_featurecounts(str(fc))
    assert cols == ["A.Aligned.sortedByCoord.out.bam", "B.Aligned.sortedByCoord.out.bam"]
    assert genes == {"G1": {"length": 100, "counts": [5, 7]}}
    sm = tmp_path / "featureCounts.txt.summary"
    sm.write_text("Status\tA.bam\tB.bam\nAssigned\t5\t7\nUnassigned_NoFeatures\t1\t2\n")
    assert rr.read_featurecounts_summary(str(sm))["B.bam"] == {"Assigned": 7, "Unassigned_NoFeatures": 2}


def test_step_metrics_follow_the_pipeline_order(tmp_path):
    paths = []
    for name in ("featurecounts", "star_align_B", "fastp_B", "star_align_A", "fastp_A", "star_index"):
        p = tmp_path / (name + ".metrics.json")
        p.write_text(json.dumps({"step": name, "wall_s": 1.0, "user_s": 1.0, "sys_s": 0.0, "peak_rss_mb": 1.0}))
        paths.append(str(p))
    steps = [s["step"] for s in rr.read_step_metrics(paths, ["A", "B"])]
    assert steps == ["star_index", "fastp_A", "fastp_B", "star_align_A", "star_align_B", "featurecounts"]


# ----------------------------------------------------------------- statistics


def test_ols_and_pearson_on_an_exact_line():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [3 + 0.5 * x for x in xs]
    slope, intercept, r2 = rr.ols(xs, ys)
    assert abs(slope - 0.5) < 1e-12 and abs(intercept - 3) < 1e-12 and abs(r2 - 1) < 1e-12
    assert abs(rr.pearson(xs, [-y for y in ys]) + 1) < 1e-12
    assert rr.pearson([1, 1, 1], [1, 2, 3]) is None


def test_bootstrap_interval_is_deterministic_and_covers_the_slope():
    xs = [float(i) for i in range(30)]
    ys = [2 * x + (0.3 if i % 2 else -0.3) for i, x in enumerate(xs)]
    lo, hi = rr.bootstrap_slope_ci(xs, ys)
    assert lo < 2 < hi and hi - lo < 0.1
    assert rr.bootstrap_slope_ci(xs, ys) == (lo, hi)  # fixed seed: the report is reproducible


def test_dose_response_of_a_linear_assay_has_slope_one():
    conc = {"E%d" % i: 2.0**i for i in range(20)}
    lengths = {e: 500 + 100 * (i % 5) for i, e in enumerate(conc)}
    # fragments proportional to molecules x length; low levels drop below the fit threshold
    counts = {e: int(round(conc[e] * lengths[e] / 1000.0 * 4)) for e in conc}
    d = rr.dose_response(counts, lengths, conc)
    assert d["detected"] == sum(1 for c in counts.values() if c > 0)
    assert d["fitted"] == sum(1 for c in counts.values() if c >= rr.MIN_FIT_COUNT) < d["detected"]
    assert abs(d["slope"] - 1) < 0.01 and d["r2"] > 0.999
    assert d["slope_ci"][0] <= d["slope"] <= d["slope_ci"][1]
    assert len(d["points"]) == 20


def test_detection_limit_is_the_lowest_fully_detected_level():
    conc = {"a": 100.0, "b": 100.0, "c": 10.0, "d": 1.0}
    reps = [{"a": 5, "b": 3, "c": 1, "d": 1}, {"a": 4, "b": 2, "c": 2, "d": 0}]
    assert rr.detection_limit(reps, conc) == 10.0  # 'd' is missed in one replicate
    assert rr.detection_limit([{"a": 0, "b": 1, "c": 1, "d": 1}], conc) is None


def test_fold_change_recovers_ratios_after_the_mrna_offset():
    rows = ercc_rows()
    table = {e: {"subgroup": g, "log2_ratio": math.log2(m1 / m2)} for e, g, m1, m2 in rows}
    offset = 1.28  # e.g. a different mRNA fraction in the two samples
    norm_a = [{e: m1 * offset * k for e, _, m1, _ in rows} for k in (1.0, 1.0)]
    norm_b = [{e: m2 for e, _, _, m2 in rows} for _ in (1, 2)]
    raw_a = [{e: 1000 for e, *_ in rows}] * 2
    raw_b = [{e: 1000 for e, *_ in rows}] * 2
    raw_b[0] = dict(raw_b[0], **{rows[0][0]: 3})  # one ERCC below the count threshold in one replicate
    f = rr.ercc_fold_change(table, norm_a, norm_b, raw_a, raw_b)
    assert f["n"] == len(rows) - 1
    assert abs(f["offset_log2"] - math.log2(offset)) < 1e-9
    for g, v in f["subgroups"].items():
        assert abs(v["expected_log2"] - math.log2(RATIOS[g])) < 1e-9
        assert abs(v["bias"]) < 1e-9 and v["rmse"] < 1e-9
    assert abs(f["pearson"] - 1) < 1e-9 and f["max_abs_subgroup_bias"] < 1e-9


def test_strandedness_is_inferred_from_the_star_columns():
    genes = {"G1": (100, 2, 98), "G2": (50, 1, 49)}
    s = rr.strandedness(genes, 2)
    assert s["inferred"] == 2 and s["matches"] and abs(s["configured_share"] - 147 / 150.0) < 1e-12
    wrong = rr.strandedness(genes, 1)
    assert not wrong["matches"] and wrong["configured_share"] < 0.1
    assert rr.strandedness({"G": (10, 5, 5)}, 0)["inferred"] == 0


def test_counter_agreement_flags_a_single_ercc_difference():
    fc = {"G1": {"length": 1, "counts": [10]}, "ERCC-1": {"length": 1, "counts": [7]}}
    star = {"G1": (0, 0, 10), "ERCC-1": (0, 0, 7)}
    ok = rr.counter_agreement(fc, 0, star, 2)
    assert ok["ercc_identical"] and ok["total_diff_pct"] == 0
    star["ERCC-1"] = (0, 0, 6)
    assert not rr.counter_agreement(fc, 0, star, 2)["ercc_identical"]


def test_replicate_correlation_ignores_genes_with_few_fragments():
    samples, groups = ["A1", "A2", "B1", "B2"], ["A", "A", "B", "B"]
    raw = {"g%d" % i: [100 + i, 101 + i, 300 - 5 * i, 299 - 5 * i] for i in range(10)}
    raw["low"] = [1, 9, 0, 2]  # below MIN_FIT_COUNT in some samples: excluded
    cpm = {g: [float(x) for x in v] for g, v in raw.items()}
    r = rr.replicate_correlation(cpm, raw, samples, groups)
    assert r["genes"] == 10
    assert r["min_within"] > 0.99 and r["max_between"] < 0
    assert {(x["a"], x["b"]) for x in r["within"]} == {("A1", "A2"), ("B1", "B2")}


# ----------------------------------------------------------------- end to end


def make_inputs(tmp_path):
    """Two UHR-like (Mix1) and two HBR-like (Mix2) samples with ERCC counts proportional to the truth."""
    rows = ercc_rows()
    write_ercc_table(tmp_path / "ercc.tsv", rows)
    samples = ["U1", "U2", "H1", "H2"]
    mixes = ["Mix1", "Mix1", "Mix2", "Mix2"]
    genes = {"G%d" % i: (1000, [200 + 3 * i, 205 + 3 * i, 40 + i, 42 + i]) for i in range(30)}
    genes["NEFH_ID"] = (2000, [5, 6, 300, 310])
    for e, _, m1, m2 in rows:
        genes[e] = (1000, [int(m1 / 30), int(m1 / 30), int(m2 / 30), int(m2 / 30)])
    bam = ["%s.Aligned.sortedByCoord.out.bam" % s for s in samples]
    with open(tmp_path / "featureCounts.txt", "w") as fh:
        fh.write('# Program:featureCounts v2.1.1; Command:"featureCounts" "-T" "4"\n')
        fh.write("\t".join(["Geneid", "Chr", "Start", "End", "Strand", "Length"] + bam) + "\n")
        for g, (length, counts) in sorted(genes.items()):
            fh.write("\t".join([g, "c", "1", "2", "+", str(length)] + [str(c) for c in counts]) + "\n")
    with open(tmp_path / "featureCounts.txt.summary", "w") as fh:
        fh.write("Status\t" + "\t".join(bam) + "\n")
        fh.write("Assigned\t" + "\t".join(str(sum(v[1][i] for v in genes.values())) for i in range(4)) + "\n")
        fh.write("Unassigned_NoFeatures\t10\t10\t10\t10\n")
    with open(tmp_path / "genes.gtf", "w") as fh:
        fh.write('c\tsrc\tgene\t1\t2\t.\t+\t.\tgene_id "NEFH_ID"; gene_name "NEFH"; gene_type "protein_coding";\n')
    logs, tabs, fastps = [], [], []
    for i, s in enumerate(samples):
        log = tmp_path / ("%s.Log.final.out" % s)
        log.write_text(
            "Number of input reads |\t1000\nUniquely mapped reads % |\t97.00%\n"
            "% of reads mapped to multiple loci |\t2.00%\nMismatch rate per base, % |\t0.13%\n"
        )
        tab = tmp_path / ("%s.ReadsPerGene.out.tab" % s)
        tab.write_text(
            "N_unmapped\t1\t1\t1\n"
            + "".join("%s\t%d\t%d\t%d\n" % (g, c[i], c[i] // 50, c[i]) for g, (_, c) in sorted(genes.items()))
        )
        fp = tmp_path / ("%s.fastp.json" % s)
        fp.write_text(
            json.dumps(
                {
                    "summary": {
                        "before_filtering": {"total_reads": 2000},
                        "after_filtering": {"total_reads": 1998, "q30_rate": 0.93},
                    }
                }
            )
        )
        logs.append(str(log))
        tabs.append(str(tab))
        fastps.append(str(fp))
    thr = tmp_path / "thr.json"
    with open(os.path.join(ROOT, "config", "rnaseq_qc_thresholds.json")) as fh:
        thr.write_text(fh.read())
    argv = [
        "--samples",
        *samples,
        "--groups",
        "UHR",
        "UHR",
        "HBR",
        "HBR",
        "--mixes",
        *mixes,
        "--counts",
        str(tmp_path / "featureCounts.txt"),
        "--counts-summary",
        str(tmp_path / "featureCounts.txt.summary"),
        "--star-logs",
        *logs,
        "--star-gene-counts",
        *tabs,
        "--fastp-json",
        *fastps,
        "--ercc",
        str(tmp_path / "ercc.tsv"),
        "--annotation",
        str(tmp_path / "genes.gtf"),
        "--qc-thresholds",
        str(thr),
        "--threads",
        "4",
        "--out-prefix",
        str(tmp_path / "out"),
    ]
    return argv


def test_report_end_to_end(tmp_path):
    assert rr.main(make_inputs(tmp_path)) == 0
    rep = json.loads((tmp_path / "out.report.json").read_text())
    assert [s["sample"] for s in rep["samples"]] == ["U1", "U2", "H1", "H2"]
    assert all(s["strandedness"]["inferred"] == 2 for s in rep["samples"])
    assert all(s["counter_agreement"]["ercc_identical"] for s in rep["samples"])
    fold = rep["ercc_fold_change"]
    assert (fold["numerator"], fold["denominator"]) == ("UHR", "HBR")
    assert fold["max_abs_subgroup_bias"] < 0.05
    nefh = next(m for m in rep["markers"] if m["gene"] == "NEFH")
    assert nefh["found"] and nefh["agrees"] and nefh["log2fc"] < -4
    assert not next(m for m in rep["markers"] if m["gene"] == "PRAME")["found"]
    assert rep["checks"] and {c["name"] for c in rep["checks"]} >= {"min ERCC dose-response R2"}
    counts = (tmp_path / "out.counts.tsv").read_text()
    assert counts.startswith("gene_id\tgene_name\tgene_type\tlength\tU1\tU2\tH1\tH2\n")
    assert "featureCounts" not in counts and "NEFH_ID\tNEFH\tprotein_coding\t2000\t5\t6\t300\t310" in counts
    md = (tmp_path / "out.report.md").read_text()
    assert "## Точность кратности по ERCC (UHR / HBR)" in md


def test_report_refuses_misaligned_sample_lists(tmp_path):
    argv = make_inputs(tmp_path)
    i = argv.index("--groups")
    argv[i + 1 : i + 5] = ["UHR", "UHR", "HBR"]
    with pytest.raises(SystemExit):
        rr.main(argv)


# ----------------------------------------------------------------- CWL policy


def load(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        return yaml.load(fh)


def read_text(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        return fh.read()


def test_star_writes_a_thread_independent_bam():
    """Coordinate sort keyed by (position, input read number); no staging paths in the header."""
    text = read_text("cwl/tools/star-align.cwl")
    args = [a for a in load("cwl/tools/star-align.cwl")["arguments"] if isinstance(a, str)]
    i = args.index("--outSAMtype")
    assert args[i + 1 : i + 3] == ["BAM", "SortedByCoordinate"]
    prefixes = {a.get("prefix") for a in load("cwl/tools/star-align.cwl")["arguments"] if isinstance(a, dict)}
    assert "--outTmpDir" not in prefixes and "--outTmpDir" not in args and "runtime.tmpdir" not in text
    assert "$(inputs.reads_1.basename)" in text and "$(inputs.index.basename)" in text
    assert "GeneCounts" in text  # the second, independent counter used by the report


def test_featurecounts_counts_fragments_with_the_configured_strand():
    doc = load("cwl/tools/featurecounts.cwl")
    assert "-p" in doc["arguments"] and "--countReadPairs" in doc["arguments"]
    assert doc["inputs"]["strandedness"]["default"] == 2
    job = load("cwl/jobs/rnaseq-uhr-hbr.yml")
    assert job["strandedness"] == 2


def test_rnaseq_workflow_collects_metrics_of_every_step():
    wf = load("cwl/workflows/rnaseq.cwl")
    measured = {name for name, step in wf["steps"].items() if "metrics" in step["out"]}
    sources = {s.split("/")[0] for s in wf["outputs"]["step_metrics"]["outputSource"]}
    assert measured == sources
    assert set(wf["steps"]["report"]["in"]["step_metrics"]["source"]) == set(
        wf["outputs"]["step_metrics"]["outputSource"]
    )


def test_scattered_steps_get_one_metrics_name_per_sample():
    """valueFrom on a scattered step sees the scattered input only through inputs.* (D-21)."""
    wf = load("cwl/workflows/rnaseq.cwl")
    assert wf["steps"]["fastp"]["in"]["step_name"] == {"valueFrom": "fastp_$(inputs.sample)"}
    assert "star_align_$(inputs.sample)" in read_text("cwl/tools/star-align.cwl")
