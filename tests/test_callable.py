"""callable_sites.py: the GQ track of a gVCF, AN by known genotypes and the series summary
(synthetic data, no containers)."""

import gzip
import json

import callable_sites as cs

SEQ = "ACGT" * 25  # contig c, 100 bp: G at 11 and 31
HEAD = "##fileformat=VCFv4.2\n##contig=<ID=c,length=100>\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS\n"


def write_gvcf(path, records):
    """records: (pos, ref, alt, end or None, gt, gq)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as fh:
        fh.write(HEAD)
        for pos, ref, alt, end, gt, gq in records:
            info = "END=%d" % end if end else "."
            fh.write("c\t%d\t.\t%s\t%s\t0\t.\t%s\tGT:GQ\t%s:%d\n" % (pos, ref, alt, info, gt, gq))


def write_vcf(path, records):
    """records: (pos, ref, alt, gt)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt") as fh:
        fh.write(HEAD)
        for pos, ref, alt, gt in records:
            fh.write("c\t%d\t.\t%s\t%s\t50\tPASS\t.\tGT\t%s\n" % (pos, ref, alt, gt))


def test_gq_track_keeps_the_lowest_gq_and_marks_gq_zero_as_covered(tmp_path):
    g = tmp_path / "s.g.vcf.gz"
    write_gvcf(
        g,
        [
            (1, "A", "<*>", 10, "0/0", 30),
            (5, "A", "<*>", 6, "0/0", 12),  # overlaps the first block with a lower GQ
            (11, "G", "T,<*>", None, "0/1", 0),
            (12, "T", "<*>", 20, "./.", 50),  # no genotype
        ],
    )
    t = cs.gq_track(str(g))["c"]
    assert (t[1], t[5], t[6], t[10]) == (30, 12, 12, 30)
    assert t[11] == 1  # GQ 0 is covered, but never confident
    assert t[12] == 0 and t[20] == 0


def test_cohort_af_leaves_unknown_genotypes_out_of_ac_and_an():
    key = ("c", 11, "G", "T")
    confident = {"c": bytearray([0] * 10 + [40] * 10)}
    missing = {"c": bytearray(20)}
    low = {"c": bytearray([0] * 11 + [8] + [0] * 8)}  # called, but with GQ 8
    res = cs.cohort_af([(confident, {key: 1}), (missing, {}), (low, {key: 1})], {key: 1}, 20)
    e = res["het"]
    assert e["sites"] == 1 and e["truth_af"] == 0.5
    assert abs(e["naive_af_mean"] - 2 / 6.0) < 1e-9 and e["honest_af_mean"] == 0.5
    assert abs(e["unknown_share_mean"] - 2 / 3.0) < 1e-9
    assert e["naive_off_by_0_1"] == 1.0 and e["honest_off_by_0_1"] == 0.0
    assert res["hom"] == {"sites": 0} and res["sites_without_known"] == 0
    # nobody is confident: the site has no AN at all and is counted apart
    res = cs.cohort_af([(missing, {}), (low, {key: 1})], {key: 1}, 20)
    assert res["sites_without_known"] == 1 and res["het"] == {"sites": 0}


def test_series_summary_end_to_end(tmp_path):
    (tmp_path / "ref.fa").write_text(">c\n%s\n" % SEQ)
    (tmp_path / "bed.bed").write_text("c\t0\t100\n")
    strat = tmp_path / "strat"
    strat.mkdir()
    (strat / "strata.tsv").write_text("all_difficult\tdiff.bed\nnot_in_all_difficult\teasy.bed\n")
    (strat / "diff.bed").write_text("c\t25\t40\n")
    (strat / "easy.bed").write_text("c\t0\t25\nc\t40\t100\n")
    write_vcf(tmp_path / "truth.vcf.gz", [(11, "G", "T", "0|1"), (31, "G", "T", "1|1")])
    series = tmp_path / "depth"
    for name, depth in (("f1.0_s1", 30.0), ("f0.29_s1", 9.0)):
        run = series / name / "run"
        run.mkdir(parents=True)
        (run / "HG002.report.json").write_text(json.dumps({"alignment": {"mean_depth": depth}}))
    dv = series / "f1.0_s1" / "deepvariant"
    write_gvcf(
        dv / "HG002.deepvariant.g.vcf.gz",
        [
            (1, "A", "<*>", 10, "0/0", 40),
            (11, "G", "T,<*>", None, "0/1", 40),
            (12, "T", "<*>", 30, "0/0", 40),
            (31, "G", "T,<*>", None, "1/1", 15),  # a hom call that is not confident
            (32, "T", "<*>", 100, "0/0", 40),
        ],
    )
    write_vcf(dv / "HG002.deepvariant.vcf.gz", [(11, "G", "T", "0/1"), (31, "G", "T", "1/1")])
    dv = series / "f0.29_s1" / "deepvariant"
    write_gvcf(dv / "HG002.deepvariant.g.vcf.gz", [(1, "A", "<*>", 100, "0/0", 5)])
    write_vcf(dv / "HG002.deepvariant.vcf.gz", [(11, "G", "T", "0/1")])
    out, md = tmp_path / "callable.json", tmp_path / "callable.md"
    argv = [str(series), "--bed", str(tmp_path / "bed.bed"), "--truth", str(tmp_path / "truth.vcf.gz")]
    argv += ["--strata", str(strat), "--ref", str(tmp_path / "ref.fa"), "--json", str(out), "--md", str(md)]
    assert cs.main(argv) == 0
    res = json.loads(out.read_text())
    top, low = res["points"]
    assert (top["mean_depth"], top["bases_confident"], top["truth_sites_confident"]) == (30.0, 0.99, 0.5)
    assert (top["truth_sites_low"], top["truth_sites_low_difficult"], top["truth_sites_difficult"]) == (1, 1, 1)
    assert low["bases_confident"] == 0.0
    cohort = res["cohorts"]["all"]
    assert cohort["samples"] == 2 and cohort["het"]["naive_af_mean"] == 0.5 and cohort["het"]["honest_af_mean"] == 0.5
    assert cohort["sites_without_known"] == 1  # the hom site: GQ 15 and GQ 5
    assert res["cohorts"]["ge20x"]["samples"] == 1
    text = md.read_text()
    assert "## Когорта из копий одного генома" in text and "GQ < 20 у 1 позиций" in text
