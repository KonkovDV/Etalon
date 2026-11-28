"""The SVG figures in docs/assets are drawn from evidence.json and committed reports.

A picture cannot carry <!--ev:...--> marks, so lint_claims.py does not see its
numbers. Instead the figures are drawn again here and compared with the committed
files: a stale picture (old test count, old run) fails the test.
"""

import json
import os

import pytest

import render_depth_figure as rd
import render_infographic as ri
import render_rnaseq_figure as rf

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "docs", "assets")


def load(path):
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        return json.load(fh)


def committed(name):
    with open(os.path.join(ASSETS, name), encoding="utf-8") as fh:
        return fh.read()


@pytest.mark.parametrize("theme", sorted(ri.THEMES))
def test_wgs_figures_match_evidence(theme):
    ev, ref = load("evidence.json"), load("docs/results/reference/HG002.report.json")
    for name, svg in (
        ("pipeline", ri.pipeline_svg(ev, ref, theme)),
        ("pipeline-narrow", ri.pipeline_narrow_svg(ev, ref, theme)),
        ("accuracy", ri.accuracy_svg(ref, theme)),
        ("accuracy-narrow", ri.accuracy_narrow_svg(ref, theme)),
    ):
        assert committed("%s-%s.svg" % (name, theme)) == svg + "\n", "run scripts/render_infographic.py"


@pytest.mark.parametrize("theme", sorted(ri.THEMES))
def test_ercc_figures_match_the_rnaseq_report(theme):
    rep = load("docs/results/rnaseq/rnaseq.report.json")
    for name, svg in (("ercc", rf.ercc_svg(rep, theme)), ("ercc-narrow", rf.ercc_narrow_svg(rep, theme))):
        assert committed("%s-%s.svg" % (name, theme)) == svg + "\n", "run scripts/render_rnaseq_figure.py"


@pytest.mark.parametrize("theme", sorted(ri.THEMES))
def test_depth_figures_match_the_curve(theme):
    res = load("docs/results/depth/curve.json")
    for name, svg in (("depth", rd.depth_svg(res, theme)), ("depth-narrow", rd.depth_narrow_svg(res, theme))):
        assert committed("%s-%s.svg" % (name, theme)) == svg + "\n", "run scripts/render_depth_figure.py"
