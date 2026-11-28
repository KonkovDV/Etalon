#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""measure.py -- run one pipeline step and record its resource usage as JSON.

    python3 measure.py --step bwa_mem2 --out bwa_mem2.metrics.json -- <command ...>

Why a separate wrapper instead of GNU time or the runner's own logs:
  * it is staged into every CWL step through InitialWorkDirRequirement, so
    the numbers are a regular workflow output under any runner (cwltool, Toil,
    Slurm) and with any image, including third-party ones such as hap.py;
  * it works with Python 2.7 (biocontainers hap.py) and Python 3.

Two memory figures are recorded, because for a shell pipeline (a | b) they differ:
  max_rss_mb        getrusage(RUSAGE_CHILDREN).ru_maxrss: the exact peak RSS of
                    the single largest process in the tree (what GNU time %M shows);
  tree_rss_peak_mb  sampled sum of RSS over the whole process tree (every
                    --interval seconds, from /proc): concurrent memory of a pipe.
  peak_rss_mb       max of the two -- the figure to use for --mem / ramMin.
The sampled value is a lower bound: spikes shorter than the interval are missed.
"""

from __future__ import division, print_function

import argparse
import json
import os
import resource
import signal
import socket
import subprocess
import sys
import threading
import time

__version__ = "1.1.0"

try:
    PAGE_KB = os.sysconf("SC_PAGE_SIZE") // 1024
except (ValueError, OSError, AttributeError):  # pragma: no cover
    PAGE_KB = 4


def _cpu_count():
    try:
        return len(os.sched_getaffinity(0))  # respects cgroup/taskset (Slurm)
    except AttributeError:  # Python 2
        import multiprocessing

        return multiprocessing.cpu_count()


def _read_ppid_map():
    """pid -> ppid for every visible process (Linux /proc)."""
    ppid = {}
    try:
        names = os.listdir("/proc")
    except OSError:
        return ppid
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % name) as fh:
                data = fh.read()
        except (IOError, OSError):
            continue  # process exited between listdir and open
        # comm (field 2) may contain spaces and ')' -- split on the LAST ')'
        rest = data[data.rfind(")") + 2 :].split()
        if len(rest) > 1:
            ppid[int(name)] = int(rest[1])
    return ppid


def _rss_kb(pid):
    try:
        with open("/proc/%d/statm" % pid) as fh:
            return int(fh.read().split()[1]) * PAGE_KB
    except (IOError, OSError, IndexError, ValueError):
        return 0


def tree_rss_kb(root_pid):
    """Sum of RSS (kB) of root_pid and all its descendants."""
    ppid = _read_ppid_map()
    children = {}
    for pid, parent in ppid.items():
        children.setdefault(parent, []).append(pid)
    total, stack, seen = 0, [root_pid], set()
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        total += _rss_kb(pid)
        stack.extend(children.get(pid, ()))
    return total


class Sampler(threading.Thread):
    def __init__(self, pid, interval):
        threading.Thread.__init__(self)
        self.daemon = True
        self.pid = pid
        self.interval = interval
        self.peak_kb = 0
        self.samples = 0
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.is_set():
            kb = tree_rss_kb(self.pid)
            if kb > self.peak_kb:
                self.peak_kb = kb
            self.samples += 1
            self._stop_event.wait(self.interval)

    def stop(self):
        self._stop_event.set()


def _utc_now():
    # time.gmtime works the same on Python 2.7 and 3.x (utcnow is deprecated in 3.12)
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--step", required=True, help="step name written to the JSON")
    p.add_argument("--out", required=True, help="path of the JSON metrics file")
    p.add_argument("--threads", type=int, default=None, help="threads given to the tool (for CPU-efficiency figures)")
    p.add_argument(
        "--interval",
        type=float,
        default=float(os.environ.get("MEASURE_INTERVAL", "0.2")),
        help="RSS sampling interval, s (env MEASURE_INTERVAL)",
    )
    p.add_argument("cmd", nargs=argparse.REMAINDER, help="-- command [args...]")
    args = p.parse_args(argv)
    if args.cmd and args.cmd[0] == "--":
        args.cmd = args.cmd[1:]
    if not args.cmd:
        p.error("no command given after --")
    return args


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    start_utc = _utc_now()
    t0 = time.time()
    proc = subprocess.Popen(args.cmd)

    def _forward(signum, _frame):  # Slurm sends SIGTERM before SIGKILL on timeout
        try:  # noqa: SIM105 - contextlib.suppress does not exist in Python 2.7 (hap.py image)
            proc.send_signal(signum)
        except OSError:
            pass

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _forward)

    sampler = Sampler(proc.pid, args.interval)
    sampler.start()
    rc = proc.wait()
    wall = time.time() - t0
    sampler.stop()
    sampler.join(1.0)

    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
    max_rss_kb = ru.ru_maxrss  # kilobytes on Linux
    cpu_s = ru.ru_utime + ru.ru_stime
    exit_code = rc if rc >= 0 else 128 - rc  # negative = killed by signal
    record = {
        "step": args.step,
        "exit_code": exit_code,
        "wall_s": round(wall, 3),
        "user_s": round(ru.ru_utime, 3),
        "sys_s": round(ru.ru_stime, 3),
        "cpu_pct": round(100.0 * cpu_s / wall, 1) if wall > 0 else None,
        "threads": args.threads,
        "cpu_efficiency": (round(cpu_s / (wall * args.threads), 3) if args.threads and wall > 0 else None),
        "max_rss_mb": round(max_rss_kb / 1024.0, 1),
        "tree_rss_peak_mb": round(sampler.peak_kb / 1024.0, 1),
        "peak_rss_mb": round(max(max_rss_kb, sampler.peak_kb) / 1024.0, 1),
        "rss_samples": sampler.samples,
        "sample_interval_s": args.interval,
        "io_read_mb": round(ru.ru_inblock * 512 / 1048576.0, 1),
        "io_write_mb": round(ru.ru_oublock * 512 / 1048576.0, 1),
        "major_page_faults": ru.ru_majflt,
        "start_utc": start_utc,
        "end_utc": _utc_now(),
        "host": socket.gethostname(),
        "cpus_available": _cpu_count(),
        "python": "%d.%d.%d" % sys.version_info[:3],
        "measure_version": __version__,
        "cmd": args.cmd,
    }
    with open(args.out, "w") as fh:
        json.dump(record, fh, indent=2, sort_keys=True)
        fh.write("\n")
    sys.stderr.write(
        "[measure] %(step)s exit=%(exit_code)s wall=%(wall_s)ss cpu=%(cpu_pct)s%% peak_rss=%(peak_rss_mb)sMB\n" % record
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
