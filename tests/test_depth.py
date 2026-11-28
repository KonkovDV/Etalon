"""Accuracy against depth: depth_curve.py, the depth keys of build_evidence.py and the
make_job override that the series relies on (synthetic inputs, no containers)."""

import json
import os

import build_evidence as be
import depth_curve as dc
import make_job

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def depth_point(frac, seed, depth, f1, f):
    row = {"f1": f1, "f1_ci": [f1 - 0.01, f1 + 0.01]}
    truth = {"SNP": row, "INDEL": row, "patent": {"f": f, "truth_in_denominator_share": 0.9, "pass": f > 0.999}}
    return {
        "label": "f%s_s%d" % (frac, seed),
        "fraction": frac,
        "seed": seed,
        "pairs": 1000,
        "mean_depth": depth,
        "callers": {"bcftools": {"giab_v5.0q": truth, "giab_v4.2.1": truth}},
    }


def write_report(run, pairs, depth):
    run.mkdir(parents=True)
    report = {"reads": {"pairs_before": pairs}, "alignment": {"mean_depth": depth}}
    (run / "HG002.report.json").write_text(json.dumps(report))


def test_read_point_takes_depth_from_the_report_and_f_from_the_patent_metric(tmp_path, monkeypatch):
    point = tmp_path / "f0.29_s2"
    write_report(point / "run", 1000, 10.8)
    (point / "run" / "giab_v5.0q.summary.csv").write_text("")  # bcftools is scored inside run/
    (point / "strelka2").mkdir()
    (point / "strelka2" / "giab_v5.0q.summary.csv").write_text("")
    (point / "deepvariant").mkdir()  # started but not scored: no entry
    vcfs = {}

    def fake_evaluate(paths, truth_dir, ref):
        vcfs.update(paths)
        lit = {"bcftools": 0.999, "strelka2": 0.9995}
        return {
            t: {
                c: {"literal": {"f": f, "numerator": 1, "denominator": 1, "truth_in_denominator_share": 0.4}}
                for c, f in lit.items()
            }
            for t in dc.TRUTHS
        }

    rows = {"SNP": {"f1": 0.9}, "INDEL": {"f1": 0.8}}
    monkeypatch.setattr(dc, "read_caller", lambda d: {"truths": dict.fromkeys(dc.TRUTHS, rows)})
    monkeypatch.setattr(dc, "slim", lambda row: row)
    monkeypatch.setattr(dc, "evaluate", fake_evaluate)
    p = dc.read_point(str(point), "truth", "ref.fa")
    assert (p["fraction"], p["seed"], p["pairs"], p["mean_depth"]) == (0.29, 2, 1000, 10.8)
    assert sorted(p["callers"]) == ["bcftools", "strelka2"]
    assert vcfs["strelka2"] == str(point / "strelka2" / "HG002.strelka2.vcf.gz")
    assert vcfs["bcftools"] == str(point / "run" / "HG002.vcf.gz")
    # the patent asks for F above 99.9 %, so exactly 99.9 % does not pass
    assert not p["callers"]["bcftools"]["giab_v4.2.1"]["patent"]["pass"]
    assert p["callers"]["strelka2"]["giab_v5.0q"]["patent"]["pass"]
    assert p["callers"]["strelka2"]["giab_v5.0q"]["SNP"]["f1"] == 0.9


def test_replicate_spread_is_min_and_max_over_seeds():
    pts = [depth_point(0.58, 1, 20.0, 0.95, 0.998), depth_point(0.58, 2, 20.1, 0.96, 0.9995)]
    pts.append(depth_point(1.0, 1, 34.5, 0.98, 0.9991))
    spread = dc.replicate_spread(pts)
    assert list(spread) == ["0.58"]
    e = spread["0.58"]
    assert e["seeds"] == [1, 2] and e["depths"] == [20.0, 20.1]
    assert e["bcftools giab_v5.0q SNP F1"] == [0.95, 0.96]
    assert e["bcftools giab_v4.2.1 F"] == [0.998, 0.9995]
    md = dc.render_md({"points": pts, "replicates": spread})
    assert "34.5x" in md and "✓" in md and "## Повторы" in md


def test_main_skips_unfinished_points_and_orders_by_depth(tmp_path, monkeypatch):
    series = tmp_path / "depth"
    for name in ("f0.58_s2", "f1.0_s1", "f0.58_s1"):
        write_report(series / name / "run", 1000, 20.0)
    (series / "f0.29_s1" / "reads").mkdir(parents=True)  # thinned, pipeline not run yet
    (series / "notes").mkdir()

    def fake_point(path, truth_dir, ref):
        frac, seed = dc.POINT.match(os.path.basename(path)).groups()
        return depth_point(float(frac), int(seed), 34.5 * float(frac), 0.95, 0.9995)

    monkeypatch.setattr(dc, "read_point", fake_point)
    out = tmp_path / "curve.json"
    assert dc.main([str(series), "--json", str(out), "--md", str(tmp_path / "curve.md")]) == 0
    res = json.loads(out.read_text())
    assert [p["label"] for p in res["points"]] == ["f1.0_s1", "f0.58_s1", "f0.58_s2"]
    assert list(res["replicates"]) == ["0.58"] and res["threshold"] == 0.999
    assert (tmp_path / "curve.md").read_text().startswith("# Точность от глубины")


def test_depth_keys_of_the_evidence_follow_the_committed_curve():
    with open(os.path.join(ROOT, "docs", "results", "depth", "curve.json"), encoding="utf-8") as fh:
        curve = json.load(fh)
    claims = be.depth_claims()
    seed1 = [p for p in curve["points"] if p["seed"] == 1]
    assert claims["depth_points"] == str(len(seed1))
    assert be.depth_tag(0.145) == "f145" and be.depth_tag(1.0) == "f1000" and be.depth_tag(0.58) == "f580"
    for p in seed1:
        tag = be.depth_tag(p["fraction"])
        assert claims["depth_%s_x" % tag] == "%.1f" % p["mean_depth"]
        pat = p["callers"]["bcftools"]["giab_v4.2.1"]["patent"]
        assert claims["depth_%s_bcftools_den_v421" % tag] == str(pat["denominator"])
        assert int(claims["depth_%s_bcftools_err_v421" % tag]) == pat["denominator"] - pat["numerator"]
    passing = sum(p["callers"]["deepvariant"]["giab_v4.2.1"]["patent"]["pass"] for p in seed1)
    assert claims["depth_pass_v421_dv"] == str(passing)
    for frac in curve["replicates"]:
        assert claims["depth_rep_%s_seeds" % be.depth_tag(float(frac))] == "3"


def test_make_job_keeps_the_format_of_an_overridden_file(tmp_path, capsys):
    reads = tmp_path / "thinned_R1.fastq.gz"
    reads.write_text("")
    rc = make_job.main(
        [
            "--for",
            os.path.join(ROOT, "cwl", "workflows", "mini-wgs.cwl"),
            os.path.join(ROOT, "cwl", "jobs", "hg002-chr20.yml"),
            "reads_1=" + str(reads),
        ]
    )
    assert rc == 0
    job = json.loads(capsys.readouterr().out)
    # the workflow input declares format: edam:format_1930, and cwltool checks it
    assert job["reads_1"] == {
        "class": "File",
        "location": str(reads),
        "format": "http://edamontology.org/format_1930",
    }
