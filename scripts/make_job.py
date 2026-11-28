#!/usr/bin/env python3
"""Merge a CWL job file with key=value overrides into a self-contained JSON job.

    python3 scripts/make_job.py cwl/jobs/hg002-chr20.yml threads=2 'mpileup_profile=""' > job.json
    python3 scripts/make_job.py --for cwl/workflows/call-strelka2.cwl cwl/jobs/hg002-chr20.yml \
        bam=results/run/HG002.bam reference=data/ref/ref.fa > job.json

cwltool takes either a job file or command-line inputs, not both, so variants
of one job (thread count, caller profile) are produced from the base file.
Values are parsed as JSON when possible (2 -> int, "" -> empty string), else
kept as strings. Relative `location`/`path` entries become absolute, so the
merged job can live anywhere (results dir, Slurm spool).

With --for WORKFLOW.cwl only the inputs of that workflow are kept (one base
job serves the main workflow and the caller workflows), and a value given for
a File/Directory input is turned into a CWL File/Directory with an absolute path.
"""

import json
import os
import sys

try:
    from ruamel.yaml import YAML  # shipped with cwltool
except ImportError:  # pragma: no cover
    YAML = None


def load(path):
    with open(path, encoding="utf-8") as fh:
        if path.endswith(".json") or YAML is None:
            return json.load(fh)
        return YAML(typ="safe").load(fh)


def absolutize(node, base):
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k in ("location", "path") and isinstance(v, str) and "://" not in v and not os.path.isabs(v):
                v = os.path.normpath(os.path.join(base, v))
            out[k] = absolutize(v, base)
        return out
    if isinstance(node, list):
        return [absolutize(x, base) for x in node]
    return node


def parse_value(text):
    try:
        return json.loads(text)
    except ValueError:
        return text


def workflow_inputs(path):
    """input name -> type name without '?' ("File", "int", "string[]", ...)."""
    inputs = load(path).get("inputs", {})
    if isinstance(inputs, list):
        inputs = {i["id"].lstrip("#"): i for i in inputs}
    out = {}
    for name, spec in inputs.items():
        t = spec.get("type") if isinstance(spec, dict) else spec
        out[name] = t.rstrip("?") if isinstance(t, str) else t
    return out


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        sys.stderr.write(__doc__)
        return 0 if argv else 2
    types = None
    if argv[0] == "--for":
        if len(argv) < 3:
            sys.stderr.write("usage: make_job.py --for WORKFLOW.cwl JOB [key=value ...]\n")
            return 2
        types = workflow_inputs(argv[1])
        argv = argv[2:]
    job = absolutize(load(argv[0]), os.path.dirname(os.path.abspath(argv[0])))
    for item in argv[1:]:
        key, sep, value = item.partition("=")
        if not sep:
            sys.stderr.write("override must be key=value: %s\n" % item)
            return 2
        key = key.lstrip("-")
        if types is not None and types.get(key) in ("File", "Directory"):
            new = {"class": types[key], "location": os.path.abspath(value)}
            old = job.get(key)
            if isinstance(old, dict) and "format" in old:  # keep the EDAM format of the job file
                new["format"] = old["format"]
            job[key] = new
        else:
            job[key] = parse_value(value)
    if types is not None:
        unknown = sorted(set(job) - set(types))
        job = {k: v for k, v in job.items() if k in types}
        if unknown:
            sys.stderr.write("not inputs of this workflow, dropped: %s\n" % ", ".join(unknown))
    json.dump(job, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
