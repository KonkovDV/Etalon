"""build_evidence: source_paths in a throwaway git repository; cohort estimates."""

import subprocess

import pytest


def test_cohort_estimates_scale_linearly_with_the_number_of_genomes():
    import build_evidence as be

    ref = be.load("docs/results/reference/HG002.report.json")
    cram = be.load("docs/results/cram/cram.json")
    c = be.cohort_claims(ref, cram["formats"])
    assert c["cohort_120k"] == "120 000"
    # the same per-genome numbers as the 100 000-genome estimates of the report and of the CRAM table, times 1.2
    assert cram["assumptions"]["cohort"] == 100_000
    cpu_100k = ref["scaling"]["cpu_hours_100k_genomes_lower_bound"] / 1e6
    assert float(c["cpu_mh_120k_lb"]) == pytest.approx(1.2 * cpu_100k, abs=0.05)
    f = {x["format"]: x for x in cram["formats"]}
    assert float(c["cram_bam_120k_pb"]) == pytest.approx(1.2 * f["BAM"]["cohort_pb"], abs=0.05)
    assert float(c["cram_v31_120k_pb"]) == pytest.approx(1.2 * f["CRAM 3.1"]["cohort_pb"], abs=0.05)
    saving_100k = f["BAM"]["cohort_pb"] - f["CRAM 3.1"]["cohort_pb"]
    assert float(c["cram_saving_v31_120k_pb"]) == pytest.approx(1.2 * saving_100k, abs=0.05)


def test_source_paths_include_untracked_but_not_ignored(tmp_path, monkeypatch):
    import build_evidence as be

    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / ".gitignore").write_text("__pycache__/\n/scripts/node_modules/\n")
    (tmp_path / "scripts" / "__pycache__").mkdir(parents=True)
    (tmp_path / "scripts" / "node_modules").mkdir()
    (tmp_path / "scripts" / "a.py").write_text("tracked")
    git("add", "scripts/a.py")
    (tmp_path / "scripts" / "b.py").write_text("new, not added yet")
    (tmp_path / "scripts" / "__pycache__" / "a.cpython.pyc").write_text("cache")
    (tmp_path / "scripts" / "node_modules" / "x.js").write_text("dependency")
    (tmp_path / "Makefile").write_text("all:")
    monkeypatch.setattr(be, "ROOT", str(tmp_path))
    before = be.source_hash()
    assert be.source_paths() == ["Makefile", "scripts/a.py", "scripts/b.py"]
    # committing the new files does not change the hash (D-16)
    git("add", "-A")
    assert be.source_hash() == before
    # a tracked file deleted from the working copy is not hashed
    (tmp_path / "scripts" / "a.py").unlink()
    assert be.source_paths() == ["Makefile", "scripts/b.py"]
