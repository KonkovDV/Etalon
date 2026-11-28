#!/usr/bin/env python3
"""QC gate: fail the CI job when a run is worse than the thresholds.

    python3 scripts/qc_gate.py results/run/HG002.report.json --junit results/qc-junit.xml

Reads the checks that make_report.py computed against config/qc_thresholds.json,
prints them, optionally writes a JUnit XML (GitLab shows it in the merge request
"Tests" tab, GitHub Actions in the job summary) and exits 1 if any check failed.
"""

import argparse
import json
import sys
from xml.sax.saxutils import escape, quoteattr


def junit(checks, suite="qc_gate"):
    failures = sum(1 for c in checks if not c["pass"])
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<testsuites><testsuite name=%s tests="%d" failures="%d">' % (quoteattr(suite), len(checks), failures),
    ]
    for c in checks:
        out.append("<testcase classname=%s name=%s>" % (quoteattr(suite), quoteattr(c["name"])))
        if not c["pass"]:
            out.append(
                "<failure message=%s>%s</failure>"
                % (
                    quoteattr("%s = %s, required %s %s" % (c["name"], c["value"], c["op"], c["limit"])),
                    escape(json.dumps(c, ensure_ascii=False)),
                )
            )
        out.append("</testcase>")
    out.append("</testsuite></testsuites>")
    return "\n".join(out) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("report_json")
    p.add_argument("--junit", help="write JUnit XML here")
    a = p.parse_args(argv)
    with open(a.report_json, encoding="utf-8") as fh:
        rep = json.load(fh)
    checks = rep.get("checks", [])
    if not checks:
        sys.stderr.write("qc_gate: no checks in report (thresholds file not passed?)\n")
        return 2
    width = max(len(c["name"]) for c in checks)
    for c in checks:
        value = "n/a" if c["value"] is None else "%.4f" % c["value"]
        print("%s  %-*s %10s %s %s" % ("PASS" if c["pass"] else "FAIL", width, c["name"], value, c["op"], c["limit"]))
    if a.junit:
        with open(a.junit, "w", encoding="utf-8") as fh:
            fh.write(junit(checks))
    failed = [c for c in checks if not c["pass"]]
    print("qc_gate: %d/%d checks passed" % (len(checks) - len(failed), len(checks)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
