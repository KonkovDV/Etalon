"""make_job, qc_gate, results_db and the report renderers on the committed reference run."""

import json
import os
import sqlite3
import xml.etree.ElementTree as ET
from contextlib import closing

import pytest

import make_job
import qc_gate
import render_html
import results_db

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "docs", "results", "reference", "HG002.report.json")


@pytest.fixture(scope="module")
def report():
    with open(REF, encoding="utf-8") as fh:
        return json.load(fh)


# --------------------------------------------------------------- make_job
def test_make_job_overrides_and_absolute_paths(tmp_path, capsys):
    rc = make_job.main(
        [os.path.join(ROOT, "cwl/jobs/hg002-chr20.yml"), "threads=2", 'mpileup_profile=""', "truth_names=[]"]
    )
    assert rc == 0
    job = json.loads(capsys.readouterr().out)
    assert job["threads"] == 2 and job["mpileup_profile"] == "" and job["truth_names"] == []
    assert os.path.isabs(job["reads_1"]["location"])
    assert job["reads_1"]["location"].endswith("data/reads/HG002_R1.fastq.gz")


def test_make_job_rejects_malformed_override(capsys):
    assert make_job.main([os.path.join(ROOT, "cwl/jobs/hg002-chr20.yml"), "threads"]) == 2


# --------------------------------------------------------------- qc_gate
def test_qc_gate_passes_reference_and_writes_junit(tmp_path, report):
    junit = tmp_path / "qc.xml"
    assert qc_gate.main([REF, "--junit", str(junit)]) == 0
    suite = ET.parse(junit).getroot().find("testsuite")
    assert suite.get("failures") == "0" and int(suite.get("tests")) == len(report["checks"])


def test_qc_gate_fails_when_a_check_fails(tmp_path, report):
    bad = dict(report)
    bad["checks"] = [dict(c) for c in report["checks"]]
    bad["checks"][0]["pass"] = False
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad))
    junit = tmp_path / "qc.xml"
    assert qc_gate.main([str(path), "--junit", str(junit)]) == 1
    assert ET.parse(junit).getroot().find("testsuite").get("failures") == "1"


# --------------------------------------------------------------- results_db
def test_to_grch38_coordinates():
    assert results_db.to_grch38("chr20_10000001_12000000", 1) == ("chr20", 10000001)
    assert results_db.to_grch38("chr20_10000001_12000000", 637684) == ("chr20", 10637684)
    assert results_db.to_grch38("chrM", 5) == ("chrM", 5)


def test_results_db_ingest_is_idempotent(tmp_path, report):
    import gzip

    run = tmp_path / "run1"
    run.mkdir()
    (run / "HG002.report.json").write_text(json.dumps(report))
    with gzip.open(run / "HG002.vcf.gz", "wt") as fh:
        fh.write("##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tHG002\n")
        fh.write("chr20_10000001_12000000\t637926\t.\tT\tC\t222.3\tPASS\t.\tGT:DP:AD\t0/1:50:22,28\n")
        fh.write("chr20_10000001_12000000\t700000\t.\tA\tG,T\t99\tPASS\t.\tGT:DP:AD\t1/2:30:0,15,15\n")
    db = str(tmp_path / "r.sqlite")
    for _ in range(2):  # second ingest replaces, does not duplicate
        assert results_db.main(["--db", db, "ingest", str(run)]) == 0
    with closing(sqlite3.connect(db)) as con:
        assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
        sql = "SELECT grch38_pos, alt, alt_count, ad_alt FROM variants ORDER BY grch38_pos, alt"
        rows = con.execute(sql).fetchall()
        assert rows == [(10637926, "C", 1, 28), (10700000, "G", 1, 15), (10700000, "T", 1, 15)]
        af = con.execute("SELECT af FROM v_allele_frequency WHERE grch38_pos = 10637926").fetchone()[0]
        assert af == 0.5  # one heterozygous sample
        n_bench = con.execute("SELECT COUNT(*) FROM benchmark WHERE filter = 'PASS' AND subset = '*'").fetchone()[0]
        assert n_bench == 4  # 2 truth sets x SNP/INDEL


def write_run(tmp_path, name, sample, report, calls, blocks):
    """A run directory with report.json, a VCF of `calls` and a gVCF of `blocks` (start, end, gq)."""
    import gzip

    run = tmp_path / name
    run.mkdir()
    rep = dict(report, sample=sample)
    (run / ("%s.report.json" % sample)).write_text(json.dumps(rep))
    head = "##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\t%s\n" % sample
    with gzip.open(run / ("%s.vcf.gz" % sample), "wt") as fh:
        fh.write(head)
        for pos, gt in calls:
            fh.write("chr20_10000001_12000000\t%d\t.\tT\tC\t50\tPASS\t.\tGT:DP:AD\t%s:30:15,15\n" % (pos, gt))
    with gzip.open(run / ("%s.g.vcf.gz" % sample), "wt") as fh:
        fh.write(head)
        for start, end, gq in blocks:
            fh.write("chr20_10000001_12000000\t%d\t.\tA\t<*>\t0\t.\tEND=%d\tGT:GQ\t0/0:%d\n" % (start, end, gq))
    return run


def test_allele_frequency_counts_only_samples_with_a_known_genotype(tmp_path, report):
    """At 100: A is a confident het, B has no confident genotype, C has a call with GQ 8.

    AN = 2N counts all three samples and C's call; the honest view keeps only A."""
    db = str(tmp_path / "r.sqlite")
    a = write_run(tmp_path, "a", "A", report, [(100, "0/1")], [(1, 99, 40), (100, 100, 35), (101, 1000, 40)])
    b = write_run(tmp_path, "b", "B", report, [], [(1, 90, 40), (91, 110, 5), (111, 1000, 40)])
    c = write_run(tmp_path, "c", "C", report, [(100, "0/1")], [(1, 99, 40), (100, 100, 8), (101, 1000, 40)])
    for run, sample in ((a, "A"), (b, "B"), (c, "C")):
        assert results_db.main(["--db", db, "ingest", str(run), "--gvcf", str(run / ("%s.g.vcf.gz" % sample))]) == 0
    with closing(sqlite3.connect(db)) as con:
        naive = con.execute("SELECT ac, an, af FROM v_allele_frequency WHERE grch38_pos = 10000100").fetchone()
        honest = con.execute(
            "SELECT ac, an, af, n_unknown FROM v_allele_frequency_callable WHERE grch38_pos = 10000100"
        ).fetchone()
        assert naive == (2, 6, 0.3333)
        assert honest == (1, 2, 0.5, 2)  # B and C are unknown: no data and GQ 8
        # GQ below the threshold splits B's intervals: 91-110 is not confident
        rows = con.execute("SELECT start, end FROM callable WHERE run_id = 'b' ORDER BY start").fetchall()
        assert rows == [(10000001, 10000090), (10000111, 10001000)]
        assert con.execute("SELECT start, end FROM callable WHERE run_id = 'a'").fetchall() == [(10000001, 10001000)]


def test_callable_intervals_merge_adjacent_blocks(tmp_path):
    import gzip

    path = tmp_path / "s.g.vcf.gz"
    with gzip.open(path, "wt") as fh:
        fh.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS\n")
        fh.write("c\t1\t.\tA\t<*>\t0\t.\tEND=10\tGT:GQ\t0/0:30\n")
        fh.write("c\t11\t.\tAT\tA\t40\tPASS\t.\tGT:GQ\t0/1:35\n")
        fh.write("c\t13\t.\tA\t<*>\t0\t.\tEND=20\tGT:GQ\t0/0:25\n")
        fh.write("c\t21\t.\tA\t<*>\t0\t.\tEND=30\tGT:GQ\t./.:0\n")
    assert results_db.callable_intervals(str(path)) == [("c", 1, 20)]


# --------------------------------------------------------------- renderers
def test_html_report_is_self_contained(report):
    page = render_html.render(report)
    assert page.startswith("<!doctype html>") and page.rstrip().endswith("</html>")
    assert "<script src" not in page and "<link" not in page  # no external resources
    for heading in ("Точность против эталонов GIAB", "Спектр замен", "Распределение глубины", "Время и память"):
        assert heading in page
    assert page.count("<svg") >= 5


def test_html_report_without_benchmark(report):
    cohort = dict(report, benchmark={}, checks=[c for c in report["checks"] if "giab" not in c["name"]])
    page = render_html.render(cohort)
    assert "Точность против эталонов GIAB" not in page and "Время и память" in page


def test_markdown_report_mentions_every_truth_set(report):
    import make_report

    md = make_report.render_markdown(report)
    assert "### giab_v5.0q" in md and "### giab_v4.2.1" in md
    assert "порог качества: пройден" in md


# --------------------------------------------------------------- site
def test_site_builds_with_csp_and_no_leaked_placeholders(tmp_path):
    import re

    import build_site

    out = tmp_path / "site"
    assert build_site.main(["--out", str(out), "--commit", "test"]) == 0
    pages = sorted(p for p in out.rglob("*.html") if p.parent.name != "report")
    assert (out / "index.html").exists() and (out / "404.html").exists() and (out / "report" / "index.html").exists()
    assert len(pages) == len(build_site.DOCS) + 3  # + index, 404, docs/index
    for page in pages:
        text = page.read_text(encoding="utf-8")
        assert 'http-equiv="Content-Security-Policy"' in text, page.name
        assert "<script" not in text, page.name  # site pages carry no JavaScript at all
        visible = re.sub(r"<[^>]+>", " ", text)
        assert not re.search(r"\b(None|NaN|undefined)\b", visible), page.name
    # every relative link on the overview page resolves to a file of the site
    index = (out / "index.html").read_text(encoding="utf-8")
    for href in re.findall(r'href="(?![a-z]+:)([^"#]+)', index):  # relative links only
        assert (out / href).exists(), href


def test_overview_photos_have_alt_text_and_both_sizes(tmp_path):
    import re

    import build_site

    out = tmp_path / "site"
    assert build_site.main(["--out", str(out), "--commit", "test"]) == 0
    index = (out / "index.html").read_text(encoding="utf-8")
    photos = re.findall(r'<figure class="photo[^"]*"><img ([^>]*)>', index)
    assert len(photos) >= 5
    for attrs in photos:
        src = re.search(r'\bsrc="([^"]+)"', attrs).group(1)
        srcset = re.search(r'\bsrcset="([^"]+)"', attrs).group(1)
        files = [src] + [part.split()[0] for part in srcset.split(",")]
        for f in files:
            assert (out / f).stat().st_size > 10_000, f  # the file is there and is a real image
        assert set(re.findall(r"\b(\d+)w\b", srcset)) == {"768", "1536"}
        alt = re.search(r'\balt="([^"]*)"', attrs).group(1)
        assert len(alt) > 40, alt  # the alt text says what is in the photo
    # only the first photo is fetched eagerly; the rest wait until they scroll into view
    assert index.count('fetchpriority="high"') == 1
    assert index.count('loading="lazy" decoding="async"') == len(photos) - 1


def test_markdown_pictures_get_their_narrow_variants():
    import build_site

    written = (
        '<picture>\n<source media="(prefers-color-scheme: dark)" srcset="../assets/depth-dark.svg">\n'
        '<img src="../assets/depth-light.svg" alt="F &amp; F1" width="100%">\n</picture>'
    )
    out = build_site.with_narrow_variants(written, "docs/metrics.html")
    assert 'srcset="../assets/depth-narrow-dark.svg"' in out and 'srcset="../assets/depth-narrow-light.svg"' in out
    assert 'alt="F &amp; F1"' in out  # unescaped once, escaped once: no double escaping
    # a figure without a narrow variant on disk stays as written
    other = written.replace("depth", "no-such-figure")
    assert build_site.with_narrow_variants(other, "docs/metrics.html") == other


def test_card_text_keeps_a_short_label_with_its_sentence():
    import build_site

    assert build_site.first_sentence("docs/REPRODUCIBILITY.md").startswith("Цель: один и тот же вход")
    assert build_site.first_sentence("docs/SPRAVKA.md").startswith("Что проверено в проекте Etalon")
