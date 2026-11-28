"""compare_callers and make_job --for on synthetic hap.py outputs (no containers)."""

import gzip
import json
import os

import compare_callers as cc
import make_job

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SUMMARY_HEADER = (
    "Type,Filter,TRUTH.TOTAL,TRUTH.TP,TRUTH.FN,QUERY.TOTAL,QUERY.FP,QUERY.UNK,FP.gt,FP.al,"
    "METRIC.Recall,METRIC.Precision,METRIC.Frac_NA,METRIC.F1_Score"
)


def write_summary(path, snp, indel):
    """snp/indel: (tp, fn, fp)."""
    lines = [SUMMARY_HEADER]
    for vtype, (tp, fn, fp) in (("SNP", snp), ("INDEL", indel)):
        rec, prec = tp / (tp + fn), tp / (tp + fp)
        f1 = 2 * rec * prec / (rec + prec)
        for filt in ("ALL", "PASS"):
            lines.append(
                "%s,%s,%d,%d,%d,%d,%d,0,0,0,%f,%f,0,%f" % (vtype, filt, tp + fn, tp, fn, tp + fp, fp, rec, prec, f1)
            )
    path.write_text("\n".join(lines) + "\n")


def write_happy_vcf(path, rows):
    """rows: (pos, ref, alt, truth_gt, truth_bd, vtype, filter)."""
    with gzip.open(path, "wt") as fh:
        fh.write("##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tTRUTH\tQUERY\n")
        for pos, ref, alt, gt, bd, vt, filt in rows:
            fh.write("c\t%d\t.\t%s\t%s\t.\t%s\t.\tGT:BD:BVT\t%s:%s:%s\t.:.:.\n" % (pos, ref, alt, filt, gt, bd, vt))


def make_run(tmp_path, name, snp, indel, calls, metrics=None):
    d = tmp_path / name
    d.mkdir()
    for truth in cc.TRUTHS:
        write_summary(d / (truth + ".summary.csv"), snp, indel)
        write_happy_vcf(d / (truth + ".vcf.gz"), calls)
    for step, wall, user in metrics or ():
        (d / (step + ".metrics.json")).write_text(
            json.dumps({"step": step, "wall_s": wall, "user_s": user, "sys_s": 1.0, "peak_rss_mb": 100.0, "threads": 4})
        )
    return str(d)


def test_mcnemar_exact_known_values():
    assert cc.mcnemar_exact(0, 0) == 1.0
    assert cc.mcnemar_exact(5, 5) == 1.0
    # 0 vs 6 discordant pairs: 2 * 0.5**6
    assert abs(cc.mcnemar_exact(0, 6) - 2 * 0.5**6) < 1e-12
    # symmetric and bounded by 1
    assert cc.mcnemar_exact(6, 24) == cc.mcnemar_exact(24, 6) < 0.01


def test_truth_key_trims_alleles_and_ignores_phase():
    # CAT -> CT written with a padding base on the right equals C -> "" shifted
    assert cc.trim_alleles(10, "CATG", ["CTG"]) == (10, "CA", ("C",))
    assert cc.truth_key("c", "10", "CATG", ["CTG"], "0|1") == cc.truth_key("c", "10", "CAT", ["CT"], "1/0")
    # only the alleles present in GT are part of the key
    assert cc.truth_key("c", "5", "A", ["G", "T"], "0/2") == "c:5:A:T"


def test_happy_truth_calls_counts_only_pass(tmp_path):
    p = tmp_path / "h.vcf.gz"
    write_happy_vcf(
        p,
        [
            (1, "A", "G", "0/1", "TP", "SNP", "PASS"),
            (2, "C", "T", "1/1", "TP", "SNP", "LowQual"),  # matched by a filtered call
            (3, "G", "A", "0/1", "FN", "SNP", "."),
            (4, "AT", "A", "0/1", "TP", "INDEL", "PASS"),
            (5, "T", "C", "0/1", "UNK", "SNP", "."),  # not a truth variant
        ],
    )
    calls = cc.happy_truth_calls(str(p))
    assert calls["SNP"] == {"c:1:A:G": True, "c:2:C:T": False, "c:3:G:A": False}
    assert calls["INDEL"] == {"c:4:AT:A": True}


def test_compare_pairs_discordant_truth_variants(tmp_path):
    base_calls = [(i, "A", "G", "0/1", "TP", "SNP", "PASS") for i in range(1, 9)]
    base_calls += [(i, "A", "G", "0/1", "FN", "SNP", ".") for i in range(9, 11)]
    other_calls = [(i, "A", "G", "0/1", "TP", "SNP", "PASS") for i in range(3, 11)]
    other_calls += [(i, "A", "G", "0/1", "FN", "SNP", ".") for i in range(1, 3)]
    a = make_run(tmp_path, "a", (8, 2, 1), (5, 5, 5), base_calls, [("bcftools_call", 10.0, 20.0), ("fastp", 3, 3)])
    b = make_run(tmp_path, "b", (8, 2, 0), (6, 4, 2), other_calls, [("strelka2_germline", 30.0, 60.0)])
    res = cc.compare({"bcftools": a, "strelka2": b}, "bcftools")
    snp = res["mcnemar"]["giab_v5.0q"]["strelka2"]["SNP"]
    assert (snp["pairs"], snp["only_base"], snp["only_other"], snp["unpaired"]) == (10, 2, 2, 0)
    assert snp["p"] == 1.0
    bench = res["benchmark"]["giab_v5.0q"]["strelka2"]["INDEL"]
    assert (bench["tp"], bench["fn"], bench["fp"]) == (6, 4, 2)
    assert bench["f1_ci"][0] < bench["f1"] < bench["f1_ci"][1]
    # only the calling steps of each caller are counted
    assert res["resources"]["bcftools"] == {
        "steps": ["bcftools_call"],
        "wall_s": 10.0,
        "cpu_s": 21.0,
        "peak_rss_mb": 100.0,
        "threads": 4,
    }
    md = cc.render_md(res)
    assert "bcftools → strelka2" in md and "## giab_v4.2.1" in md


def test_cli_writes_json_markdown_and_export(tmp_path):
    calls = [(1, "A", "G", "0/1", "TP", "SNP", "PASS")]
    a = make_run(tmp_path, "a", (8, 2, 1), (5, 5, 5), calls, [("bcftools_call", 1.0, 1.0)])
    b = make_run(tmp_path, "b", (8, 2, 0), (6, 4, 2), calls, [("strelka2_germline", 2.0, 2.0)])
    out = tmp_path / "out"
    rc = cc.main(
        ["x=" + a, "y=" + b, "--json", str(tmp_path / "c.json"), "--md", str(tmp_path / "c.md"), "--export", str(out)]
    )
    assert rc == 0
    assert json.loads((tmp_path / "c.json").read_text())["base"] == "x"
    assert (out / "y" / "giab_v5.0q.summary.csv").exists()
    assert (out / "x" / "step_metrics.tsv").read_text().startswith("step\twall_s")
    # the exported directory can be compared again without VCFs (no McNemar then)
    res = cc.compare({"x": str(out / "x"), "y": str(out / "y")}, "x")
    assert res["mcnemar"] == {} and res["resources"]["x"]["wall_s"] == 1.0
    assert cc.main(["nodir=/does/not/exist"]) == 2
    assert cc.main(["x=" + a, "--base", "zzz"]) == 2


def test_make_job_for_keeps_only_workflow_inputs_and_builds_files(tmp_path, capsys):
    bam = tmp_path / "x.bam"
    bam.write_text("")
    rc = make_job.main(
        [
            "--for",
            os.path.join(ROOT, "cwl/workflows/call-strelka2.cwl"),
            os.path.join(ROOT, "cwl/jobs/hg002-chr20.yml"),
            "bam=" + str(bam),
            "threads=2",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    job = json.loads(captured.out)
    assert job["bam"] == {"class": "File", "location": str(bam)}
    assert job["threads"] == 2 and job["truth_names"] == ["giab_v5.0q", "giab_v4.2.1"]
    assert "reads_1" not in job and "mpileup_profile" not in job
    assert "reads_1" in captured.err
    assert make_job.main(["--for", "only.cwl"]) == 2
