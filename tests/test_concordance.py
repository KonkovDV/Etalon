"""concordance.py: the RU 2846268 genotype-concordance metric on synthetic VCFs."""

import gzip
import json

import concordance as c

#        1234567890
SEQ = "GATTACCCCCAGTAGCATG"  # homopolymer of C at 6-10


def rec(pos, ref, alt, gt="0/1", filt="PASS", gq=50, ad="10,10", chrom="c"):
    return {
        "chrom": chrom,
        "pos": pos,
        "ref": ref,
        "alts": alt.split(","),
        "filter": filt,
        "gt": gt,
        "gq": gq,
        "ad": sum(int(x) for x in ad.split(",")) if ad else None,
    }


def test_left_normalize_shifts_indels_in_a_homopolymer():
    seqs = {"c": SEQ}
    # deletion of one C written at the right end of the run, and at the left end
    right = c.left_normalize(9, "CC", "C", SEQ)
    left = c.left_normalize(5, "AC", "A", SEQ)
    assert right == left == (5, "AC", "A")
    # padding on the right is trimmed, SNVs are left alone
    assert c.left_normalize(2, "ATT", "GTT", SEQ) == (2, "A", "G")
    assert c.left_normalize(3, "T", "G", SEQ) == (3, "T", "G")
    assert list(c.split_records(rec(9, "CC", "C"), seqs)) == [(5, "AC", "A", (0, 1))]


def test_split_multiallelic_recodes_genotype_like_bcftools():
    seqs = {"c": SEQ}
    out = list(c.split_records(rec(3, "T", "G,A", gt="1|2"), seqs))
    assert out == [(3, "T", "G", (0, 1)), (3, "T", "A", (0, 1))]
    assert list(c.split_records(rec(3, "T", "G,<NON_REF>", gt="1/1"), seqs)) == [(3, "T", "G", (1, 1))]
    # literal mode keeps the ALT field as written
    assert list(c.split_records(rec(3, "T", "G,A", gt="1/2"))) == [(3, "T", "G,A", (1, 2))]


def test_genotype_quality_falls_back_to_pl_and_filters_apply():
    assert c.genotype_quality({"GQ": "37"}) == 37.0
    assert c.genotype_quality({"PL": "250,0,31"}) == 31.0  # bcftools: no GQ, second-smallest PL
    assert c.genotype_quality({"PL": "."}) is None
    assert c.allele_depth({"AD": "3,8"}) == 11 and c.allele_depth({}) is None
    assert c.passes(rec(1, "G", "A"), 10, 10)
    assert not c.passes(rec(1, "G", "A", gq=10), 10, 10)  # strictly greater than 10
    assert not c.passes(rec(1, "G", "A", ad="5,5"), 10, 10)
    assert not c.passes(rec(1, "G", "A", filt="LowQual"), 10, 10)
    assert not c.passes(rec(1, "G", "A", ad=None), 10, 10)


def test_f_ignores_missed_and_extra_calls():
    truth = [rec(p, "G", "A") for p in range(1, 11)]
    calls = [rec(p, "G", "A") for p in range(1, 11)]
    calls[0]["gt"] = "1/1"  # one wrong genotype
    full = c.patent_f(calls, truth)
    assert (full["numerator"], full["denominator"]) == (9, 10)
    # half of the true variants missed: F is unchanged, only the share in the denominator drops
    half = c.patent_f(calls[:5], truth)
    assert half["f"] == 4 / 5 and half["truth_in_denominator_share"] == 0.5
    # 100 false calls: F is unchanged, they never enter the denominator
    noisy = c.patent_f(calls + [rec(p, "T", "C") for p in range(100, 200)], truth)
    assert noisy["f"] == full["f"] and noisy["query_without_exact_match"] == 100
    # calls failing GQ/AD/PASS are left out of both counts
    weak = c.patent_f([dict(r, gq=5) for r in calls], truth)
    assert weak["denominator"] == 0 and weak["f"] is None


def test_differently_written_indel_counts_only_after_normalization():
    seqs = {"c": SEQ}
    truth = [rec(5, "AC", "A"), rec(3, "T", "G")]
    calls = [rec(9, "CC", "C"), rec(3, "T", "G")]  # same deletion, right-shifted
    lit = c.patent_f(calls, truth)
    norm = c.patent_f(calls, truth, seqs)
    assert (lit["denominator"], norm["denominator"]) == (1, 2)
    assert lit["query_without_exact_match"] == 1 and norm["query_without_exact_match"] == 0


def test_bed_restricts_both_sides(tmp_path):
    bed_path = tmp_path / "r.bed"
    bed_path.write_text("c\t0\t5\nc\t3\t8\nother\t10\t20\n")
    bed = c.read_bed(str(bed_path))
    assert bed["c"] == ([0], [8])  # overlapping intervals merged
    assert c.in_bed(bed, "c", 1) and c.in_bed(bed, "c", 8) and not c.in_bed(bed, "c", 9)
    assert not c.in_bed(bed, "x", 1) and c.in_bed(None, "x", 1)
    truth = [rec(2, "G", "A"), rec(12, "G", "A")]
    calls = [rec(2, "G", "A"), rec(12, "G", "C")]
    res = c.patent_f(calls, truth, None, bed)
    assert (res["denominator"], res["truth_total"], res["query_passing_filters"]) == (1, 1, 1)


def write_vcf(path, rows, fmt="GT:GQ:AD"):
    with gzip.open(path, "wt") as fh:
        fh.write("##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS\n")
        for pos, ref, alt, sample in rows:
            fh.write("c\t%d\t.\t%s\t%s\t50\tPASS\t.\t%s\t%s\n" % (pos, ref, alt, fmt, sample))


def test_cli_end_to_end(tmp_path):
    truth_dir = tmp_path / "truth"
    truth_dir.mkdir()
    for t in c.TRUTHS:
        write_vcf(str(truth_dir / (t + ".vcf.gz")), [(5, "AC", "A", "0/1:.:."), (3, "T", "G", "1/1:.:.")])
        (truth_dir / (t + ".bed")).write_text("c\t0\t19\n")
    strata = tmp_path / "strat"
    strata.mkdir()
    (strata / "hp.bed").write_text("c\t4\t10\n")
    (strata / "strata.tsv").write_text("homopolymers_ge7\thp.bed\n")
    ref = tmp_path / "ref.fa"
    ref.write_text(">c\n%s\n" % SEQ)
    q = tmp_path / "q.vcf.gz"
    write_vcf(str(q), [(9, "CC", "C", "0/1:40:9,9"), (3, "T", "G", "0/1:40:0,20")])
    out = tmp_path / "f.json"
    md = tmp_path / "f.md"
    happy = tmp_path / "compare.json"
    row = {"f1": 0.9, "fn": 1, "fp": 2}
    happy.write_text(json.dumps({"benchmark": {"giab_v5.0q": {"x": {"SNP": row, "INDEL": row}}}}))
    argv = ["--truth-dir", str(truth_dir), "--ref", str(ref), "--strata", str(strata), "x=" + str(q)]
    assert c.main(argv + ["--json", str(out), "--md", str(md), "--compare", str(happy)]) == 0
    res = json.loads(out.read_text())["results"]["giab_v5.0q"]["x"]
    assert res["literal"]["denominator"] == 1 and res["literal"]["f"] == 0.0  # 0/1 against 1/1
    assert res["normalized"]["denominator"] == 2 and res["normalized"]["f"] == 0.5
    assert res["strata"]["homopolymers_ge7"]["denominator"] == 1
    assert "| x | 0.000 (0/1) | 50.000 (1/2)" in md.read_text() and "0.9000" in md.read_text()
    assert c.main(["--truth-dir", str(truth_dir), "x=/no/such.vcf"]) == 2


def test_norm_check_reports_differences(tmp_path):
    ref = tmp_path / "ref.fa"
    ref.write_text(">c\n%s\n" % SEQ)
    q = tmp_path / "q.vcf.gz"
    write_vcf(str(q), [(9, "CC", "C", "0/1:40:9,9"), (3, "T", "G,A", "1/2:40:0,20")])
    (tmp_path / "q.bcftools.tsv").write_text("c\t5\tAC\tA\t0/1\nc\t3\tT\tG\t1/0\nc\t3\tT\tA\t0/1\nc\t3\tT\t*\t0/1\n")
    md, diff = c.norm_check(str(ref), str(tmp_path), [str(q)])
    assert diff == 0 and "Итог: 3 записей, расхождений 0." in md
    (tmp_path / "q.bcftools.tsv").write_text("c\t9\tCC\tC\t0/1\n")
    assert c.main(["norm-check", str(ref), str(tmp_path), str(q)]) == 1
    assert c.main(["norm-check", str(ref)]) == 2


def test_split_only_separates_multiallelic_effect_from_left_shift():
    seqs = {"c": SEQ}
    truth = [rec(5, "AC", "A"), rec(3, "T", "G,A", gt="1/2")]
    calls = [rec(9, "CC", "C"), rec(3, "T", "G"), rec(3, "T", "A")]
    lit = c.patent_f(calls, truth)
    split = c.patent_f(calls, truth, seqs, left_align=False)
    norm = c.patent_f(calls, truth, seqs)
    # literal: nothing matches; splitting recovers the two SNVs; the shift recovers the deletion
    assert (lit["denominator"], split["denominator"], norm["denominator"]) == (0, 2, 3)
    assert lit["truth_multiallelic"] == 1 and lit["query_multiallelic"] == 0
    assert c.trim_only(3, "TAC", "GAC") == (3, "T", "G")
