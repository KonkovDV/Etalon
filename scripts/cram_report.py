#!/usr/bin/env python3
"""BAM против CRAM: таблица из scripts/check_cram.sh и грубая оценка для когорты.

    python3 scripts/cram_report.py results/cram --json docs/results/cram/cram.json --md docs/results/cram/cram.md

Оценка для генома и когорты — линейный пересчёт участка: размер файла растёт с числом
оснований генома, покрытых ридами, и с глубиной. Это порядок величины, а не прогноз:
на полном геноме есть сегментные дупликации, невыровненные риды и другая доля дубликатов,
поэтому настоящее соотношение CRAM и BAM может отличаться на несколько процентов.
"""

import argparse
import csv
import json
import os
import sys

GENOME_BP = 2.9e9  # GRCh38 без участков N: столько оснований могут покрыть риды
TARGET_DEPTH = 30.0  # типичная глубина популяционного WGS
COHORT = 100_000  # когорта масштаба национальной базы частот
REPORT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "results", "reference")


def read_tsv(path):
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    for r in rows:
        r["bytes"] = int(r["bytes"])
        r["index_bytes"] = int(r["index_bytes"])
        r["write_s"] = float(r["write_s"]) if r["write_s"] else None
        r["read_s"] = float(r["read_s"])
    return rows


def build(series_dir, report_path):
    rows = read_tsv(os.path.join(series_dir, "cram.tsv"))
    with open(os.path.join(series_dir, "versions.txt"), encoding="utf-8") as fh:
        versions = [line.strip().replace("Using ", "") for line in fh if line.strip()]
    with open(report_path, encoding="utf-8") as fh:
        aln = json.load(fh)["alignment"]
    bam = next(r for r in rows if r["format"] == "BAM")
    scale = GENOME_BP / aln["contig_len"] * TARGET_DEPTH / aln["mean_depth"]
    out = {
        "versions": versions,
        "region_bp": aln["contig_len"],
        "mean_depth": aln["mean_depth"],
        "assumptions": {"genome_bp": GENOME_BP, "target_depth": TARGET_DEPTH, "cohort": COHORT, "scale": scale},
        "formats": [],
    }
    for r in rows:
        out["formats"].append(
            dict(
                r,
                share_of_bam=r["bytes"] / bam["bytes"],
                read_vs_bam=r["read_s"] / bam["read_s"],
                genome_gb=r["bytes"] * scale / 1e9,
                cohort_pb=r["bytes"] * scale * COHORT / 1e15,
            )
        )
    return out


def yes_no(value):
    return {"yes": "да", "no": "нет"}.get(value, value)


def render_md(res):
    a = res["assumptions"]
    md = ["# BAM против CRAM\n"]
    md.append(
        "HG002, участок %s п.н., %.1fx; %s. Время — на одном потоке, чтение — полное декодирование в SAM. "
        "«Записи» сравниваются с дополнительными полями как множеством: их порядок в SAM не значим, а CRAM его "
        "меняет (MD и NM не хранит, а восстанавливает при чтении).\n"
        % ("{:,}".format(res["region_bp"]).replace(",", " "), res["mean_depth"], ", ".join(res["versions"]))
    )
    md.append(
        "| формат | размер, МБ | доля от BAM | индекс, КБ | запись, с | чтение, с | SAM побайтно | записи | вызовы |"
    )
    md.append("|---|---|---|---|---|---|---|---|---|")
    for f in res["formats"]:
        md.append(
            "| %s | %.1f | %.0f %% | %.1f | %s | %.2f | %s | %s | %s |"
            % (
                f["format"],
                f["bytes"] / 1e6,
                100 * f["share_of_bam"],
                f["index_bytes"] / 1e3,
                "–" if f["write_s"] is None else "%.2f" % f["write_s"],
                f["read_s"],
                yes_no(f["sam_bytes_identical"]),
                yes_no(f["records_identical"]),
                yes_no(f["calls_identical"]),
            )
        )
    md.append("")
    md.append("## Грубая оценка для генома и когорты\n")
    md.append(
        "Линейный пересчёт: %.1f млрд п.н. генома, покрытых ридами, глубина %.0fx, когорта %s геномов. "
        "Это порядок величины, а не прогноз.\n"
        % (a["genome_bp"] / 1e9, a["target_depth"], "{:,}".format(a["cohort"]).replace(",", " "))
    )
    md.append("| формат | на геном, ГБ | на когорту, ПБ |")
    md.append("|---|---|---|")
    for f in res["formats"]:
        md.append("| %s | %.1f | %.2f |" % (f["format"], f["genome_gb"], f["cohort_pb"]))
    md.append("")
    return "\n".join(md)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("series", help="каталог scripts/check_cram.sh")
    p.add_argument("--report", default=os.path.join(REPORT, "HG002.report.json"))
    p.add_argument("--json")
    p.add_argument("--md")
    a = p.parse_args(argv)
    res = build(a.series, a.report)
    md = render_md(res)
    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=2, sort_keys=True, ensure_ascii=False)
            fh.write("\n")
    if a.md:
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write(md)
    if not (a.json or a.md):
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
