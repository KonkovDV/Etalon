"""Policy checks on the CWL files: rules that keep the pipeline measurable and reproducible.

Each rule here was learned the hard way (docs/DEBUGGING.md) or is required by the
design (docs/adr/). They are static: no container is started.
"""

import glob
import os
import re

import pytest
from ruamel.yaml import YAML

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = sorted(glob.glob(os.path.join(ROOT, "cwl", "tools", "*.cwl")))
yaml = YAML(typ="safe")


def load(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.load(fh)


def read_text(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def tool_id(path):
    return os.path.basename(path)


@pytest.mark.parametrize("path", TOOLS, ids=tool_id)
def test_every_tool_runs_in_a_container(path):
    doc = load(path)
    docker = {**doc.get("hints", {}), **doc.get("requirements", {})}.get("DockerRequirement")
    assert docker and docker.get("dockerPull"), "no DockerRequirement"


def test_third_party_images_are_pinned_by_digest():
    for path in TOOLS:
        pull = load(path)["hints"]["DockerRequirement"]["dockerPull"]
        if not pull.startswith("hg002-mini/"):  # our own image is built from a pinned Dockerfile
            assert "@sha256:" in pull, "%s: %s is not pinned by digest" % (tool_id(path), pull)


@pytest.mark.parametrize("path", [p for p in TOOLS if not p.endswith("report.cwl")], ids=tool_id)
def test_every_step_is_measured(path):
    """measure.py is staged, wraps the command and its JSON is an output (docs/adr/ADR-003)."""
    doc = load(path)
    listing = doc["requirements"]["InitialWorkDirRequirement"]["listing"]
    assert any(isinstance(e, dict) and e.get("entryname") == "measure.py" for e in listing)
    assert doc["baseCommand"][1] == "measure.py"
    assert "metrics" in doc["outputs"]


@pytest.mark.parametrize("path", TOOLS, ids=tool_id)
def test_resources_are_declared(path):
    """Toil turns ResourceRequirement into sbatch --cpus-per-task/--mem; without it every step gets defaults."""
    rr = load(path)["requirements"].get("ResourceRequirement", {})
    assert "coresMin" in rr and "ramMin" in rr


def test_included_scripts_contain_no_cwl_expressions():
    """$include'd files are scanned for $(...) and ${...}; one stray '$(' would be evaluated as JS."""
    for script in ("bin/measure.py", "scripts/make_report.py", "scripts/render_html.py", "scripts/rnaseq_report.py"):
        text = read_text(os.path.join(ROOT, script))
        assert not re.search(r"\$[({]", text), script


def test_outputs_carry_no_run_specific_paths():
    """--no-PG / --no-version keep cwltool's random staging paths out of BAM and VCF headers (D-08)."""
    text = {tool_id(p): read_text(p) for p in TOOLS}
    for name in ("samtools-sort.cwl", "samtools-markdup.cwl", "bam-finalize.cwl"):
        assert "--no-PG" in text[name], name
    assert "fixmate -m --no-PG" in text["bwa-mem2-mem.cwl"]
    for name in ("bcftools-call.cwl", "bcftools-filter.cwl"):
        assert text[name].count("--no-version") >= 2, name
    # bcftools view writes ##bcftools_viewCommand with the staging path and date (D-15)
    for name, tool in text.items():
        for call in re.findall(r"bcftools (?:view|annotate|norm|concat) +-[^\n|]*", tool):
            assert "--no-version" in call, "%s: %s" % (name, call)
    # inputs whose paths would land in headers are passed by basename
    assert "inputs.reference.basename" in text["bwa-mem2-mem.cwl"]
    assert "-f '$(inputs.reference.basename)'" in text["bcftools-call.cwl"]


def test_bwa_batch_size_is_fixed():
    """-K makes bwa-mem2 output independent of the thread count (docs/REPRODUCIBILITY.md)."""
    assert "-K $(inputs.batch_bases)" in read_text(os.path.join(ROOT, "cwl/tools/bwa-mem2-mem.cwl"))


def test_bwa_simd_build_is_chosen_by_the_cpu_unless_forced():
    """Default runs the launcher (the CPU picks the SIMD build); a forced build is only for the SIMD check."""
    tool = load(os.path.join(ROOT, "cwl/tools/bwa-mem2-mem.cwl"))
    assert tool["inputs"]["simd"]["default"] == ""
    # exec -a keeps argv[0] = "bwa-mem2", as the launcher does, so @PG CL does not name the build
    assert '$(inputs.simd ? "exec -a bwa-mem2 bwa-mem2." + inputs.simd : "bwa-mem2") mem' in read_text(
        os.path.join(ROOT, "cwl/tools/bwa-mem2-mem.cwl")
    )
    wf = load(os.path.join(ROOT, "cwl/workflows/mini-wgs.cwl"))
    assert wf["inputs"]["bwa_simd"]["default"] == ""
    assert wf["steps"]["bwa_mem2_mem"]["in"]["simd"] == "bwa_simd"


def test_fastp_does_not_use_slow_adapter_autodetection():
    """--detect_adapter_for_pe made fastp 19x slower with an identical VCF (D-05)."""
    doc = load(os.path.join(ROOT, "cwl/tools/fastp.cwl"))
    assert "--detect_adapter_for_pe" not in doc["arguments"]


def test_workflow_collects_metrics_of_every_step():
    wf = load(os.path.join(ROOT, "cwl/workflows/mini-wgs.cwl"))
    measured = {name for name, step in wf["steps"].items() if "metrics" in step["out"]}
    sources = {s.split("/")[0] for s in wf["outputs"]["step_metrics"]["outputSource"]}
    assert measured == sources
