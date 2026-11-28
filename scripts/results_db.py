#!/usr/bin/env python3
"""Results database (SQLite): runs, per-step resources, benchmark and variants.

    scripts/results_db.py ingest results/repro_t4 --label t4      # one run directory
    scripts/results_db.py summary                                 # runs side by side
    scripts/results_db.py query "SELECT * FROM v_benchmark_pass"  # any SQL

Why a database and not a folder of CSVs: questions across runs ("did the new
caller profile change INDEL precision beyond noise?", "which step needs the most
memory?", "are all VCFs of this sample identical?") become one SQL query, and the
same schema scales to many samples. The `v_allele_frequency` view shows the
population-database idea on a small scale: AF = sum of ALT alleles / (2 x number
of samples) over distinct samples, on GRCh38 coordinates. With `ingest --gvcf`,
`v_allele_frequency_callable` counts in AC and AN only the samples whose genotype is
known at the site (gVCF GQ >= 20), as a frequency database should.

Ingestion is idempotent: re-ingesting a run replaces its rows (one transaction).
Stdlib only (sqlite3, gzip, json).
"""

import argparse
import gzip
import hashlib
import json
import os
import re
import sqlite3
import sys
import time

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS runs (
    run_id          TEXT PRIMARY KEY,           -- label, unique per ingested directory
    sample          TEXT NOT NULL,
    source_dir      TEXT NOT NULL,
    ingested_utc    TEXT NOT NULL,
    threads         INTEGER,
    mpileup_profile TEXT,
    vcf_sha256      TEXT NOT NULL,              -- byte identity of the final VCF
    qc_pass         INTEGER                     -- 1/0/NULL
);
CREATE TABLE IF NOT EXISTS step_metrics (
    run_id      TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    step        TEXT NOT NULL,
    wall_s      REAL, cpu_s REAL, cpu_pct REAL, threads INTEGER,
    peak_rss_mb REAL, max_rss_mb REAL, suggested_mem_mb INTEGER,
    PRIMARY KEY (run_id, step)
);
CREATE TABLE IF NOT EXISTS benchmark (
    run_id   TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    truth    TEXT NOT NULL,                     -- giab_v5.0q, giab_v4.2.1
    type     TEXT NOT NULL,                     -- SNP / INDEL
    filter   TEXT NOT NULL,                     -- ALL / PASS
    subset   TEXT NOT NULL,                     -- '*' = whole benchmark region, else stratum
    truth_total INTEGER, tp INTEGER, fn INTEGER, fp INTEGER,
    recall REAL, recall_lo REAL, recall_hi REAL,
    precision REAL, precision_lo REAL, precision_hi REAL,
    f1 REAL, f1_lo REAL, f1_hi REAL,
    PRIMARY KEY (run_id, truth, type, filter, subset)
);
CREATE TABLE IF NOT EXISTS variants (
    run_id       TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    sample       TEXT NOT NULL,
    grch38_chrom TEXT NOT NULL,
    grch38_pos   INTEGER NOT NULL,
    ref TEXT NOT NULL, alt TEXT NOT NULL,
    qual REAL, filter TEXT, gt TEXT,
    alt_count INTEGER,                          -- ALT alleles in GT (0, 1, 2)
    dp INTEGER, ad_ref INTEGER, ad_alt INTEGER,
    PRIMARY KEY (run_id, grch38_chrom, grch38_pos, ref, alt)
);
CREATE INDEX IF NOT EXISTS variants_locus ON variants (grch38_chrom, grch38_pos);
-- Where the genotype of the sample is known: gVCF blocks and calls with GQ >= gq_min,
-- merged, on GRCh38 coordinates (1-based, inclusive). Filled by `ingest --gvcf`.
CREATE TABLE IF NOT EXISTS callable (
    run_id       TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    grch38_chrom TEXT NOT NULL,
    start        INTEGER NOT NULL,
    end          INTEGER NOT NULL,
    gq_min       INTEGER NOT NULL,
    PRIMARY KEY (run_id, grch38_chrom, start)
);
CREATE INDEX IF NOT EXISTS callable_locus ON callable (grch38_chrom, start, end);

CREATE VIEW IF NOT EXISTS v_benchmark_pass AS
    SELECT run_id, truth, type, truth_total, tp, fn, fp,
           ROUND(recall, 4) AS recall, ROUND(precision, 4) AS precision,
           ROUND(f1, 4) AS f1, ROUND(f1_lo, 4) AS f1_lo, ROUND(f1_hi, 4) AS f1_hi
    FROM benchmark WHERE filter = 'PASS' AND subset = '*';

-- One genotype per (sample, locus): the latest run of each sample wins.
CREATE VIEW IF NOT EXISTS v_allele_frequency AS
    WITH latest AS (
        SELECT sample, MAX(ingested_utc) AS t FROM runs GROUP BY sample),
    calls AS (
        SELECT v.* FROM variants v JOIN runs r USING (run_id)
        JOIN latest l ON l.sample = r.sample AND l.t = r.ingested_utc
        WHERE v.filter = 'PASS')
    SELECT grch38_chrom, grch38_pos, ref, alt,
           SUM(alt_count) AS ac,
           2 * (SELECT COUNT(*) FROM latest) AS an,
           ROUND(1.0 * SUM(alt_count) / (2 * (SELECT COUNT(*) FROM latest)), 4) AS af,
           SUM(alt_count = 2) AS n_hom_alt, SUM(alt_count = 1) AS n_het
    FROM calls GROUP BY grch38_chrom, grch38_pos, ref, alt;

-- The same, with an honest AN, as gnomAD does with its adj filter: the genotype of a sample
-- is known at a site when its callable intervals cover it (gVCF block or call with
-- GQ >= gq_min). A call outside them is left out of AC, and a sample without data is left
-- out of AN instead of being counted as homozygous reference. Only samples ingested with a
-- gVCF take part.
CREATE VIEW IF NOT EXISTS v_allele_frequency_callable AS
    WITH latest AS (
        SELECT sample, MAX(ingested_utc) AS t FROM runs GROUP BY sample),
    cohort AS (
        SELECT r.run_id, r.sample FROM runs r JOIN latest l ON l.sample = r.sample AND l.t = r.ingested_utc
        WHERE EXISTS (SELECT 1 FROM callable c WHERE c.run_id = r.run_id)),
    cov AS (
        SELECT co.sample, cb.grch38_chrom, cb.start, cb.end FROM callable cb JOIN cohort co USING (run_id)),
    calls AS (
        SELECT v.* FROM variants v JOIN cohort USING (run_id)
        WHERE v.filter = 'PASS' AND EXISTS (
            SELECT 1 FROM cov WHERE cov.sample = v.sample AND cov.grch38_chrom = v.grch38_chrom
              AND v.grch38_pos BETWEEN cov.start AND cov.end)),
    sites AS (
        SELECT grch38_chrom, grch38_pos, ref, alt, SUM(alt_count) AS ac,
               SUM(alt_count = 2) AS n_hom_alt, SUM(alt_count = 1) AS n_het
        FROM calls GROUP BY grch38_chrom, grch38_pos, ref, alt),
    known AS (
        SELECT s.grch38_chrom, s.grch38_pos, s.ref, s.alt, COUNT(DISTINCT cov.sample) AS n
        FROM sites s JOIN cov ON cov.grch38_chrom = s.grch38_chrom AND s.grch38_pos BETWEEN cov.start AND cov.end
        GROUP BY s.grch38_chrom, s.grch38_pos, s.ref, s.alt)
    SELECT s.grch38_chrom, s.grch38_pos, s.ref, s.alt, s.ac,
           2 * k.n AS an,
           ROUND(1.0 * s.ac / (2 * k.n), 4) AS af,
           (SELECT COUNT(*) FROM cohort) - k.n AS n_unknown,
           s.n_hom_alt, s.n_het
    FROM sites s JOIN known k USING (grch38_chrom, grch38_pos, ref, alt);
"""

CONTIG_RE = re.compile(r"^(?P<chrom>[^_]+)_(?P<start>\d+)_(?P<end>\d+)$")


def to_grch38(contig, pos):
    """Mini-contig 'chr20_10000001_12000000' position -> (chr20, GRCh38 position)."""
    m = CONTIG_RE.match(contig)
    if not m:
        return contig, pos
    return m.group("chrom"), pos + int(m.group("start")) - 1


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def iter_vcf(path):
    with gzip.open(path, "rt") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            f = line.rstrip("\n").split("\t")
            fmt = dict(zip(f[8].split(":"), f[9].split(":")))
            gt = fmt.get("GT", ".")
            ad = [int(x) if x.isdigit() else None for x in fmt.get("AD", "").split(",")] if fmt.get("AD") else []
            dp = fmt.get("DP")
            for i, alt in enumerate(f[4].split(",")):
                allele = str(i + 1)
                yield {
                    "contig": f[0],
                    "pos": int(f[1]),
                    "ref": f[3],
                    "alt": alt,
                    "qual": float(f[5]) if f[5] != "." else None,
                    "filter": f[6],
                    "gt": gt,
                    "alt_count": sum(1 for a in re.split(r"[/|]", gt) if a == allele),
                    "dp": int(dp) if dp and dp.isdigit() else None,
                    "ad_ref": ad[0] if ad else None,
                    "ad_alt": ad[i + 1] if len(ad) > i + 1 else None,
                }


def callable_intervals(path, gq_min=20):
    """Confident intervals of a gVCF on GRCh38: [(chrom, start, end)], merged, 1-based inclusive.

    A block or a call counts when its genotype is complete and GQ >= gq_min."""
    raw = []
    with gzip.open(path, "rt") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            f = line.rstrip("\n").split("\t")
            fmt = dict(zip(f[8].split(":"), f[9].split(":")))
            gq, gt = fmt.get("GQ", "."), fmt.get("GT", ".")
            if not gq.isdigit() or int(gq) < gq_min or "." in gt:
                continue
            m = re.search(r"(?:^|;)END=(\d+)", f[7])
            start = int(f[1])
            end = int(m.group(1)) if m else start + len(f[3]) - 1
            raw.append((f[0], start, end))
    raw.sort()
    merged = []
    for contig, start, end in raw:
        if merged and merged[-1][0] == contig and start <= merged[-1][2] + 1:
            merged[-1][2] = max(merged[-1][2], end)
        else:
            merged.append([contig, start, end])
    out = []
    for contig, start, end in merged:
        chrom, s = to_grch38(contig, start)
        out.append((chrom, s, s + (end - start)))
    return out


def _ci(row, key):
    """(lo, hi) of an interval field; (None, None) when it is missing."""
    value = row.get(key) or (None, None)
    return value[0], value[1]


# Placeholder lists are generated from fixed column counts, never from input.
INSERT_BENCHMARK = "INSERT OR REPLACE INTO benchmark VALUES (" + ",".join("?" * 18) + ")"  # noqa: S608 - fixed placeholders
INSERT_VARIANT = "INSERT OR REPLACE INTO variants VALUES (" + ",".join("?" * 13) + ")"  # noqa: S608 - fixed placeholders


def connect(path):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


def ingest(con, run_dir, label=None, gvcf=None, gq_min=20):
    report_path = next(
        (os.path.join(run_dir, f) for f in sorted(os.listdir(run_dir)) if f.endswith(".report.json")), None
    )
    if not report_path:
        raise SystemExit("no *.report.json in %s" % run_dir)
    with open(report_path, encoding="utf-8") as fh:
        rep = json.load(fh)
    sample = rep["sample"]
    vcf = os.path.join(run_dir, "%s.vcf.gz" % sample)
    run_id = label or os.path.basename(os.path.normpath(run_dir))
    with con:  # one transaction: a run is either fully in the database or not at all
        con.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        con.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)",
            (
                run_id,
                sample,
                os.path.abspath(run_dir),
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                rep.get("threads"),
                rep.get("mpileup_profile"),
                sha256(vcf),
                None if rep.get("qc_pass") is None else int(rep["qc_pass"]),
            ),
        )
        con.executemany(
            "INSERT INTO step_metrics VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    run_id,
                    s["step"],
                    s["wall_s"],
                    s["user_s"] + s["sys_s"],
                    s.get("cpu_pct"),
                    s.get("threads"),
                    s["peak_rss_mb"],
                    s["max_rss_mb"],
                    s.get("suggested_mem_mb"),
                )
                for s in rep.get("steps", [])
            ],
        )
        rows = []
        for truth, b in rep.get("benchmark", {}).items():
            for r in b["summary"] + b["strata"]:
                rows.append(
                    (
                        run_id,
                        truth,
                        r["type"],
                        r["filter"],
                        r["subset"],
                        r["truth_total"],
                        r["tp"],
                        r["fn"],
                        r["fp"],
                        r["recall"],
                        *_ci(r, "recall_ci"),
                        r["precision"],
                        *_ci(r, "precision_ci"),
                        r["f1"],
                        *_ci(r, "f1_ci"),
                    )
                )
        con.executemany(INSERT_BENCHMARK, rows)
        variants = []
        for v in iter_vcf(vcf):
            chrom, pos = to_grch38(v["contig"], v["pos"])
            variants.append(
                (
                    run_id,
                    sample,
                    chrom,
                    pos,
                    v["ref"],
                    v["alt"],
                    v["qual"],
                    v["filter"],
                    v["gt"],
                    v["alt_count"],
                    v["dp"],
                    v["ad_ref"],
                    v["ad_alt"],
                )
            )
        con.executemany(INSERT_VARIANT, variants)
        if gvcf:
            con.executemany(
                "INSERT INTO callable VALUES (?,?,?,?,?)",
                [(run_id, c, s_, e, gq_min) for c, s_, e in callable_intervals(gvcf, gq_min)],
            )
    return run_id, len(variants)


def print_rows(cur):
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    widths = [
        max(len(str(c)), *(len("" if r[i] is None else str(r[i])) for r in rows)) if rows else len(str(c))
        for i, c in enumerate(cols)
    ]
    print("  ".join(str(c).ljust(w) for c, w in zip(cols, widths)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(("" if v is None else str(v)).ljust(w) for v, w in zip(r, widths)))


SUMMARY_SQL = """
SELECT r.run_id, r.threads, COALESCE(NULLIF(r.mpileup_profile, ''), 'default') AS profile,
       substr(r.vcf_sha256, 1, 12) AS vcf_sha256,
       b.truth, b.type, b.f1, b.f1_lo, b.f1_hi, b.fp, b.fn
FROM runs r JOIN v_benchmark_pass b USING (run_id)
ORDER BY b.truth, b.type, r.run_id
"""


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--db", default=os.environ.get("RESULTS_DB", "results/results.sqlite"))
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("ingest", help="add or replace a run directory")
    i.add_argument("run_dir", nargs="+")
    i.add_argument("--label", help="run id (default: directory name); only with one run_dir")
    i.add_argument("--gvcf", help="gVCF of the sample: confident intervals for v_allele_frequency_callable")
    i.add_argument("--gq-min", type=int, default=20, help="GQ that makes a gVCF position confident")
    sub.add_parser("summary", help="benchmark of all runs side by side")
    q = sub.add_parser("query", help="run SQL and print the result")
    q.add_argument("sql")
    a = p.parse_args(argv)

    os.makedirs(os.path.dirname(os.path.abspath(a.db)), exist_ok=True)
    con = connect(a.db)
    if a.cmd == "ingest":
        if (a.label or a.gvcf) and len(a.run_dir) > 1:
            p.error("--label and --gvcf need exactly one run_dir")
        for d in a.run_dir:
            run_id, n = ingest(con, d, a.label, a.gvcf, a.gq_min)
            print("ingested %s: %d variant alleles -> %s" % (run_id, n, a.db))
    elif a.cmd == "summary":
        print_rows(con.execute(SUMMARY_SQL))
    else:
        print_rows(con.execute(a.sql))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
