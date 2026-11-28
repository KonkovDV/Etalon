#!/usr/bin/env python3
"""Fail if a JUnit report has skipped tests.

    python -m pytest --junitxml=var/junit.xml && python scripts/check_no_skips.py var/junit.xml

CI installs every dependency, so a skip there means a check silently did not
run (for example the /proc-based memory test on a non-Linux runner).
"""

import sys
from xml.etree.ElementTree import parse  # report written by pytest in the same job


def skipped(path):
    root = parse(path).getroot()
    return [
        "%s::%s" % (c.get("classname"), c.get("name")) for c in root.iter("testcase") if c.find("skipped") is not None
    ]


def main(argv):
    found = skipped(argv[1] if len(argv) > 1 else "var/junit.xml")
    if found:
        sys.stderr.write("skipped tests (not allowed in CI):\n  " + "\n  ".join(found) + "\n")
        return 1
    print("no skipped tests")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
