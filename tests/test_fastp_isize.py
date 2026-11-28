"""fastp insert-size finding (D-23): the committed results and the patch say what the docs say."""

import os
import re

import build_evidence
import make_report

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATCH = os.path.join(ROOT, "docker", "fastp-isize", "fastp-1.4.0-isize-all-threads.patch")


def rows():
    with open(os.path.join(ROOT, "docs", "results", "fastp_isize_threads.md"), encoding="utf-8") as fh:
        return build_evidence.fastp_isize_rows(fh.read())


def worker_zero_pairs(total, threads, pack=1000):
    """Pairs that worker 0 sees when packs of `pack` pairs go to the workers in turn."""
    sizes = [min(pack, total - i) for i in range(0, total, pack)]
    return sum(sizes[i] for i in range(0, len(sizes), threads))


def test_release_counts_only_the_packs_of_worker_zero():
    """fastp reads 1000 pairs per pack and hands packs to workers in turn; only worker 0 counts."""
    r = rows()
    for dataset in ("RNA-seq UHR_Rep1", "WGS HG002"):
        total = r[(dataset, "official", 1)]["evaluated"]
        for t in (2, 3, 4):
            assert r[(dataset, "official", t)]["evaluated"] == worker_zero_pairs(total, t)
            assert r[(dataset, "release", t)] == r[(dataset, "official", t)]


def test_patched_histogram_does_not_depend_on_threads_and_reads_do_not_change():
    r = rows()
    for (dataset, build, t), v in r.items():
        single = r[(dataset, "official", 1)]
        assert v["reads"] == single["reads"]  # trimming never depended on the thread count
        if build == "patched":
            assert v["hist"] == single["hist"] and v["peak"] == single["peak"]
            assert v["evaluated"] == single["evaluated"]


def test_patch_only_lifts_the_worker_zero_condition():
    with open(PATCH, encoding="utf-8") as fh:
        text = fh.read()
    assert re.findall(r"^\+\+\+ b/(\S+)", text, re.M) == ["src/peprocessor.cpp"]
    removed = [line for line in text.splitlines() if line.startswith("-") and not line.startswith("---")]
    added = [line for line in text.splitlines() if line.startswith("+") and not line.startswith("+++")]
    assert sum("getThreadId() == 0" in line for line in removed) == 3
    assert not any("getThreadId()" in line for line in added)
    assert any("statInsertSize" in line for line in added)


def test_reports_do_not_use_the_fastp_insert_size_peak():
    """make_report.py and rnaseq_report.py take insert size from samtools, never from fastp."""
    for script in ("make_report.py", "rnaseq_report.py"):
        with open(os.path.join(ROOT, "scripts", script), encoding="utf-8") as fh:
            code = fh.read()
        assert '"insert_size"' not in code and "insert_size_peak" not in code, script
    assert make_report  # imported: the module still loads
