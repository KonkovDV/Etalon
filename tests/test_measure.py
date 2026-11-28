"""measure.py: exit codes, timing and both memory figures, on real processes."""

import json
import sys

import pytest

import measure

ALLOC = "import time; b = bytearray({mb} * 1024 * 1024); b[::4096] = b'x' * len(b[::4096]); time.sleep({sleep})"


def run(tmp_path, cmd, threads=None):
    out = tmp_path / "m.json"
    argv = ["--step", "t", "--out", str(out), "--interval", "0.05"]
    if threads:
        argv += ["--threads", str(threads)]
    rc = measure.main(argv + ["--"] + cmd)
    return rc, json.loads(out.read_text())


def test_success_record_has_all_fields(tmp_path):
    rc, rec = run(tmp_path, [sys.executable, "-c", "pass"], threads=2)
    assert rc == 0 and rec["exit_code"] == 0
    for key in (
        "wall_s",
        "user_s",
        "sys_s",
        "cpu_pct",
        "max_rss_mb",
        "tree_rss_peak_mb",
        "peak_rss_mb",
        "start_utc",
        "end_utc",
        "cmd",
        "cpu_efficiency",
    ):
        assert key in rec
    assert rec["threads"] == 2


def test_exit_code_is_propagated(tmp_path):
    rc, rec = run(tmp_path, [sys.executable, "-c", "import sys; sys.exit(3)"])
    assert rc == 3 and rec["exit_code"] == 3


def test_killed_by_signal_maps_to_128_plus_signal(tmp_path):
    rc, rec = run(tmp_path, [sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"])
    assert rc == 128 + 15 and rec["exit_code"] == 143


def test_single_process_peak_memory(tmp_path):
    _, rec = run(tmp_path, [sys.executable, "-c", ALLOC.format(mb=150, sleep=0.5)])
    assert rec["max_rss_mb"] >= 150
    assert rec["peak_rss_mb"] >= rec["max_rss_mb"]


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="/proc sampling is Linux-only")
def test_pipe_memory_is_summed_over_the_process_tree(tmp_path):
    # two concurrent 120 MB processes: largest single process ~120 MB,
    # concurrent tree ~240 MB. GNU time would only report the former.
    script = ('{py} -c "{a}" & {py} -c "{a}"; wait').format(py=sys.executable, a=ALLOC.format(mb=120, sleep=1.5))
    _, rec = run(tmp_path, ["bash", "-c", script])
    assert 120 <= rec["max_rss_mb"] < 200
    assert rec["tree_rss_peak_mb"] >= 230
    assert rec["peak_rss_mb"] == rec["tree_rss_peak_mb"]


def test_wall_time(tmp_path):
    _, rec = run(tmp_path, ["sleep", "0.3"])
    assert 0.29 <= rec["wall_s"] < 2.0


def test_missing_command_is_an_error(tmp_path):
    with pytest.raises(SystemExit):
        measure.main(["--step", "t", "--out", str(tmp_path / "x.json")])
