"""shift_coords.py: coordinate arithmetic, filtering and round trips."""

import io
import random

import shift_coords as sc

HEADER = (
    "##fileformat=VCFv4.2\n"
    "##contig=<ID=chr20,length=64444167>\n"
    "##contig=<ID=chr21,length=46709983>\n"
    "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS\n"
)


def run_vcf(text, **kw):
    out = io.StringIO()
    args = {
        "from_contig": "chr20",
        "to_contig": "mini",
        "to_length": 1000,
        "shift": 10000,
        "keep_start": 10001,
        "keep_end": 11000,
    }
    args.update(kw)
    kept, dropped = sc.shift_vcf(io.StringIO(text), out, **args)
    return out.getvalue(), kept, dropped


def records(vcf_text):
    return [line.split("\t") for line in vcf_text.splitlines() if not line.startswith("#")]


def test_vcf_positions_are_shifted_and_contig_renamed():
    body = "chr20\t10500\t.\tA\tG\t50\tPASS\t.\tGT\t0/1\n"
    out, kept, dropped = run_vcf(HEADER + body)
    rec = records(out)
    assert (kept, dropped) == (1, 0)
    assert rec[0][0] == "mini" and rec[0][1] == "500"


def test_vcf_header_has_single_new_contig_and_provenance():
    out, _, _ = run_vcf(HEADER)
    contigs = [line for line in out.splitlines() if line.startswith("##contig")]
    assert contigs == ["##contig=<ID=mini,length=1000>"]
    assert "##shift_coords=<from=chr20,to=mini,shift=10000" in out
    assert out.splitlines()[-1].startswith("#CHROM")


def test_vcf_drops_other_contigs_and_records_outside_region():
    body = (
        "chr21\t10500\t.\tA\tG\t50\tPASS\t.\tGT\t0/1\n"
        "chr20\t10000\t.\tA\tG\t50\tPASS\t.\tGT\t0/1\n"  # 1 bp before region
        "chr20\t10001\t.\tA\tG\t50\tPASS\t.\tGT\t0/1\n"  # first base: kept
        "chr20\t11000\t.\tA\tG\t50\tPASS\t.\tGT\t0/1\n"  # last base: kept
        "chr20\t10998\t.\tACGT\tA\t50\tPASS\t.\tGT\t0/1\n"
    )  # REF runs past the end
    out, kept, dropped = run_vcf(HEADER + body)
    assert [r[1] for r in records(out)] == ["1", "1000"]
    assert (kept, dropped) == (2, 3)


def test_bed_is_clipped_then_shifted_and_empty_intervals_dropped():
    bed = (
        "chr20\t9000\t10100\n"  # overlaps start -> clipped to [10000, 10100)
        "chr20\t10500\t10600\n"
        "chr20\t10900\t12000\n"  # overlaps end -> [10900, 11000)
        "chr20\t20000\t20100\n"  # outside
        "chr21\t10500\t10600\n"
    )  # other contig
    out = io.StringIO()
    kept, dropped = sc.shift_bed(io.StringIO(bed), out, "chr20", "mini", 10000, 10001, 11000)
    assert out.getvalue().splitlines() == ["mini\t0\t100", "mini\t500\t600", "mini\t900\t1000"]
    assert (kept, dropped) == (3, 2)


def test_round_trip_restores_original_coordinates():
    rng = random.Random(7)
    positions = sorted(rng.sample(range(10001, 11000), 50))
    body = "".join("chr20\t%d\t.\tA\tG\t50\tPASS\t.\tGT\t0/1\n" % p for p in positions)
    forward, _, _ = run_vcf(HEADER + body)
    back = io.StringIO()
    sc.shift_vcf(
        io.StringIO(forward),
        back,
        from_contig="mini",
        to_contig="chr20",
        to_length=64444167,
        shift=-10000,
        keep_start=1,
        keep_end=1000,
    )
    assert [int(r[1]) for r in records(back.getvalue())] == positions
    assert {r[0] for r in records(back.getvalue())} == {"chr20"}


def test_cli_reads_gz_and_writes_file(tmp_path):
    import gzip

    src = tmp_path / "in.vcf.gz"
    with gzip.open(src, "wt") as fh:
        fh.write(HEADER + "chr20\t10002\t.\tC\tT\t50\tPASS\t.\tGT\t1/1\n")
    dst = tmp_path / "out.vcf"
    rc = sc.main(
        [
            "vcf",
            str(src),
            "--from-contig",
            "chr20",
            "--to-contig",
            "mini",
            "--shift",
            "10000",
            "--keep-start",
            "10001",
            "--keep-end",
            "11000",
            "--to-length",
            "1000",
            "-o",
            str(dst),
        ]
    )
    assert rc == 0
    assert records(dst.read_text())[0][:2] == ["mini", "2"]
