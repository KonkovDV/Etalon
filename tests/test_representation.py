"""representation.py on synthetic VCF and hap.py outputs (no containers)."""

import gzip

import representation as rp

# position:    1234567890123456789012345678901234567890
SEQ = "ACGTACGTTTTTTTGCATGCAGTCAGTCAACCGGTTAACCGGTTAAGG"
HEADER = "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS\n"


def write_vcf(path, rows):
    """rows: (pos, ref, alt, gt)."""
    with gzip.open(path, "wt") as fh:
        fh.write(HEADER)
        for pos, ref, alt, gt in rows:
            fh.write("c\t%d\t.\t%s\t%s\t50\tPASS\t.\tGT\t%s\n" % (pos, ref, alt, gt))


def write_happy(path, rows):
    """rows: (pos, ref, alt, truth 'GT:BD:BK' or None, query 'GT:BD:BK' or None, superlocus start)."""
    with gzip.open(path, "wt") as fh:
        fh.write("##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tTRUTH\tQUERY\n")
        for pos, ref, alt, t, q, bs in rows:
            fh.write(
                "c\t%d\t.\t%s\t%s\t.\t.\tBS=%d\tGT:BD:BK\t%s\t%s\n" % (pos, ref, alt, bs, t or ".:.:.", q or ".:.:.")
            )


def setup(tmp_path, delins_query=(("30", "A", "G"), ("31", "CC", "C"))):
    (tmp_path / "ref.fa").write_text(">c\n%s\n" % SEQ)
    (tmp_path / "bed.bed").write_text("c\t0\t%d\n" % len(SEQ))
    # A: a multi-allelic SNV, a T deletion written at the right end of the T run, a delins
    write_vcf(tmp_path / "a.vcf.gz", [(2, "C", "A,G", "1/2"), (14, "TG", "G", "0/1"), (30, "ACC", "GC", "0/1")])
    # B: the same SNVs bi-allelic, the deletion left-aligned, the delins as an SNV + a deletion
    rows = [(2, "C", "A", "0/1"), (2, "C", "G", "0/1"), (7, "GT", "G", "0/1")]
    rows += [(int(p), r, a, "0/1") for p, r, a in delins_query]
    write_vcf(tmp_path / "b.vcf.gz", rows)
    pair = tmp_path / "pairs" / "a_vs_b"
    pair.mkdir(parents=True)
    happy = [
        (2, "C", "A,G", "1/2:TP:gm", "1/2:TP:gm", 2),
        (7, "GT", "G", "0/1:TP:gm", "0/1:TP:gm", 7),
        (30, "ACC", "GC", "0/1:TP:lm", None, 30),
    ]
    happy += [(int(p), r, a, None, "0/1:TP:lm", 30) for p, r, a in delins_query]
    write_happy(pair / "happy.vcf.gz", happy)
    return {"a": str(tmp_path / "a.vcf.gz"), "b": str(tmp_path / "b.vcf.gz")}


def build(tmp_path, **kw):
    calls = setup(tmp_path, **kw)
    return rp.build(calls, str(tmp_path / "ref.fa"), str(tmp_path / "bed.bed"), str(tmp_path / "pairs"))


def test_levels_remove_what_they_should(tmp_path):
    res = build(tmp_path)
    pair = res["pairs"][0]
    # as written nothing matches; splitting fixes the multi-allelic SNV; left-alignment fixes the deletion
    assert pair["raw"]["shared"] == 0
    assert pair["split"]["shared"] == 2
    assert pair["norm"]["shared"] == 3
    assert res["union"]["raw"] > res["union"]["split"] > res["union"]["norm"]


def test_same_haplotype_written_as_delins_or_as_two_records(tmp_path):
    pair = build(tmp_path)["pairs"][0]
    # after normalisation the delins (A) and the SNV + deletion (B) still differ by key,
    # but hap.py matched them: they are one haplotype, not real differences
    assert pair["norm"]["only_a"] == 1 and pair["norm"]["only_b"] == 2
    assert pair["same_haplotype_only_a"] == 1 and pair["same_haplotype_only_b"] == 2
    assert pair["real_only_a"] == 0 and pair["real_only_b"] == 0
    assert pair["kinds"] == {"делинс против нескольких записей": 1}
    assert pair["same_haplotype_loci"] == 1 and pair["same_haplotype_loci_verified"] == 1
    ex = pair["examples"][0]
    assert ex["a"] == ["30 AC>G 0/1"] and ex["b"] == ["30 A>G 0/1", "30 AC>A 0/1"]
    # rebuilt from the reference with 6 bp of flank on each side: ACC -> GC
    assert ex["ref"] == "CAGTCAACCGGTTAA" and ex["haplotypes"] == ["CAGTCAGCGGTTAA"]


def test_a_superlocus_hap_py_matched_but_the_rebuilt_haplotypes_do_not_is_not_verified(tmp_path):
    # B now writes an SNV + a deletion of the wrong base: GCC... -> GC is not reachable
    pair = build(tmp_path, delins_query=(("30", "A", "G"), ("32", "CG", "C")))["pairs"][0]
    assert pair["same_haplotype_loci"] == 1 and pair["same_haplotype_loci_verified"] == 0
    assert pair["examples"] == []


def test_phases_are_tried_so_two_hets_can_sit_on_one_haplotype():
    # (CT)3 A C (AT)2 A: one CT unit lost and one AT unit gained, written two ways
    seq = "GCTCTCTACATATA"
    alt = "GCTCTACATATATA"
    subs = [(6, "C", ["A"], (0, 1)), (7, "T", ["C"], (0, 1)), (9, "C", ["T"], (0, 1))]
    indels = [(1, "GCT", ["G"], (0, 1)), (9, "C", ["CAT"], (0, 1))]
    a, b = rp.haplotype_pairs(subs, seq, 1, 14), rp.haplotype_pairs(indels, seq, 1, 14)
    assert tuple(sorted((seq, alt))) in a & b  # pairs are unordered, stored sorted
    # the same two indels on different haplotypes give other sequences, and those are tried too
    assert ("GCTCTACATATA", "GCTCTCTACATATATA") in b
    snvs = [("c", 6, "C", "A"), ("c", 7, "T", "C"), ("c", 9, "C", "T")]
    assert rp.kind(snvs, [("c", 1, "GCT", "G"), ("c", 9, "C", "CAT")]) == "замены против инделов"


def test_overlapping_alleles_on_one_haplotype_are_rejected():
    assert rp.apply_alleles("ACGT", 1, 4, [(2, "C", "T"), (3, "G", "A")]) == "ATAT"
    assert rp.apply_alleles("ACGT", 1, 4, [(2, "CG", "C"), (3, "G", "A")]) is None
    assert rp.apply_alleles("ACGT", 1, 4, [(2, "A", "T")]) is None  # REF does not match the reference


def test_compress_writes_short_tandem_repeats_in_brackets():
    assert rp.compress("GCTCTCTCTAC") == "G(CT)4AC"
    assert rp.compress("ATTTTTG") == "A(T)5G"
    assert rp.compress("AAAT") == "AAAT"  # three bases of a homopolymer stay as they are
    assert rp.compress("ATATAT") == "(AT)3"


def test_markdown_has_the_tables(tmp_path):
    md = rp.render_md(build(tmp_path))
    assert "## Сколько различных вариантов" in md and "## Примеры: тот же гаплотип, другая запись" in md
    assert "в 1 суперлокусах из 1" in md and "`CAGTCAACCGGTTAA` → `CAGTCAGCGGTTAA`" in md
