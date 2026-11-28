"""cram_report.py on a synthetic table from check_cram.sh (no containers)."""

import json

import cram_report as cr

TSV = (
    "format\tbytes\tindex_bytes\twrite_s\tread_s\tsam_bytes_identical\trecords_identical\tcalls_identical\n"
    "BAM\t1000000\t6000\t\t0.300\tyes\tyes\tyes\n"
    "CRAM 3.0\t340000\t800\t1.400\t0.560\tno\tyes\tyes\n"
    "CRAM 3.1\t290000\t800\t1.500\t0.480\tno\tyes\tyes\n"
)


def write_series(tmp_path):
    series = tmp_path / "cram"
    series.mkdir()
    (series / "cram.tsv").write_text(TSV)
    (series / "versions.txt").write_text("samtools 1.25\nUsing htslib 1.25\n")
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"alignment": {"contig_len": 2000000, "mean_depth": 30.0}}))
    return series, report


def test_shares_and_the_rough_cohort_estimate(tmp_path):
    series, report = write_series(tmp_path)
    res = cr.build(str(series), str(report))
    f = {x["format"]: x for x in res["formats"]}
    assert f["BAM"]["share_of_bam"] == 1.0 and abs(f["CRAM 3.1"]["share_of_bam"] - 0.29) < 1e-12
    assert f["BAM"]["write_s"] is None and f["CRAM 3.1"]["read_vs_bam"] == 0.48 / 0.3
    # 2.9 Gb / 2 Mb = 1450 regions, the same depth: 1 MB of BAM -> 1.45 GB per genome
    assert abs(f["BAM"]["genome_gb"] - 1.45) < 1e-9
    assert abs(f["BAM"]["cohort_pb"] - 1.45 * cr.COHORT / 1e6) < 1e-9
    assert res["versions"] == ["samtools 1.25", "htslib 1.25"]


def test_markdown_speaks_russian_and_main_writes_both_files(tmp_path):
    series, report = write_series(tmp_path)
    out_json, out_md = tmp_path / "out.json", tmp_path / "out.md"
    argv = [str(series), "--report", str(report), "--json", str(out_json), "--md", str(out_md)]
    assert cr.main(argv) == 0
    md = out_md.read_text()
    assert "| CRAM 3.1 | 0.3 | 29 % |" in md and "| нет | да | да |" in md and "2 000 000 п.н." in md
    assert json.loads(out_json.read_text())["assumptions"]["cohort"] == cr.COHORT
