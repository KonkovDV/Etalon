#!/usr/bin/env python3
"""Где генотип образца известен: доля позиций с уверенным генотипом по gVCF на разной глубине.

    python3 scripts/callable_sites.py results/depth --bed data/truth/giab_v5.0q.bed \\
        --truth data/truth/giab_v5.0q.vcf.gz --strata data/strat \\
        --json docs/results/depth/callable.json --md docs/results/depth/callable.md

В базе частот AN (число аллелей в знаменателе) честно считать только по образцам, у
которых в этой позиции известен генотип. gVCF DeepVariant даёт это прямо: опорные блоки
и вызовы с GQ. Позиция считается уверенной, если её покрывает запись gVCF с GQ ≥ порога
(по умолчанию 20, то есть вероятность ошибки генотипа ≤ 1 %). Если вместо этого брать
AN = 2 × число образцов, образец без данных в позиции молча засчитывается как гомозигота
по референсу, и частота занижается.

Для каждой точки серии (scripts/depth_series.sh, зерно 1) считается доля уверенных
позиций в доверенных участках эталона, в сложных участках GIAB и вне их, и доля
эталонных вариантов, в позиции которых генотип уверенный.

Потом точки серии складываются в когорту: это копии одного и того же генома на разной
глубине, поэтому правильная частота каждого эталонного варианта известна заранее (0,5 для
гетерозиготы, 1 для гомозиготы). По каждому варианту AF считается двумя способами: с
AN = 2 × число образцов и с AN только по образцам, у которых генотип в позиции известен.
"""

import argparse
import gzip
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from concordance import gt_alleles, in_bed, keyed, read_bed, read_fasta, read_strata, read_vcf  # noqa: E402

POINT = re.compile(r"^f([0-9.]+)_s1$")
GVCF = os.path.join("deepvariant", "HG002.deepvariant.g.vcf.gz")
VCF = os.path.join("deepvariant", "HG002.deepvariant.vcf.gz")
COHORTS = (("all", 0.0), ("ge20x", 20.0))  # вся серия и только точки от 20x


def gq_track(path):
    """{contig: bytearray}: минимальный GQ записи gVCF, покрывающей позицию (0 — не покрыта)."""
    tracks = {}
    with gzip.open(path, "rt") as fh:
        for line in fh:
            if line.startswith("##contig"):
                m = re.search(r"ID=([^,>]+),length=(\d+)", line)
                if m:
                    tracks[m.group(1)] = bytearray(int(m.group(2)) + 1)
                continue
            if line.startswith("#"):
                continue
            f = line.rstrip("\n").split("\t")
            fmt = dict(zip(f[8].split(":"), f[9].split(":")))
            gq = fmt.get("GQ", ".")
            if gq in (".", "") or gt_alleles(fmt.get("GT", ".")) is None:
                continue
            start = int(f[1])
            m = re.search(r"(?:^|;)END=(\d+)", f[7])
            end = int(m.group(1)) if m else start + len(f[3]) - 1
            value = min(255, int(gq)) or 1  # GQ 0 is still "covered", but not confident
            track = tracks[f[0]]
            for pos in range(start, end + 1):
                if track[pos] == 0 or value < track[pos]:
                    track[pos] = value
    return tracks


def bed_positions(bed):
    for chrom, (starts, ends) in bed.items():
        for s, e in zip(starts, ends):
            for pos in range(s + 1, e + 1):
                yield chrom, pos


def share(tracks, positions, gq_min):
    n = ok = 0
    for chrom, pos in positions:
        n += 1
        t = tracks.get(chrom)
        ok += t is not None and pos < len(t) and t[pos] >= gq_min
    return (ok / n if n else None), n


def point(path, bed, strata, truth_sites, gq_min):
    tracks = gq_track(os.path.join(path, GVCF))
    with open(os.path.join(path, "run", "HG002.report.json"), encoding="utf-8") as fh:
        depth = json.load(fh)["alignment"]["mean_depth"]
    out = {"label": os.path.basename(path), "mean_depth": depth}
    out["bases_confident"], out["bases"] = share(tracks, bed_positions(bed), gq_min)
    for name, sbed in strata.items():
        pos = [(c, p) for c, p in bed_positions(bed) if in_bed(sbed, c, p)]
        out["bases_confident_" + name], out["bases_" + name] = share(tracks, pos, gq_min)
    out["truth_sites_confident"], out["truth_sites"] = share(tracks, truth_sites, gq_min)
    low = [(c, q) for c, q in truth_sites if not (c in tracks and q < len(tracks[c]) and tracks[c][q] >= gq_min)]
    out["truth_sites_low"] = len(low)
    if "all_difficult" in strata:  # где лежат эталонные варианты с неуверенным генотипом
        out["truth_sites_low_difficult"] = sum(in_bed(strata["all_difficult"], c, q) for c, q in low)
        out["truth_sites_difficult"] = sum(in_bed(strata["all_difficult"], c, q) for c, q in truth_sites)
    return out


def called_keys(path, seqs, bed):
    """{нормализованный ключ: число копий аллели} для PASS-вызовов с ненулевым генотипом."""
    recs = [r for r in read_vcf(path) if r["filter"] in ("PASS", ".") and gt_alleles(r["gt"]) not in (None, (0, 0))]
    return {k: gt.count(1) for k, gt in keyed(recs, seqs, bed).items()}


def af_summary(rows):
    """rows: [(правильная AF, AF при AN = 2N, AF при AN по известным генотипам, доля неизвестных)]."""
    n = len(rows)
    if not n:
        return {"sites": 0}

    def mean(i):
        return sum(r[i] for r in rows) / n

    return {
        "sites": n,
        "truth_af": rows[0][0],
        "naive_af_mean": mean(1),
        "honest_af_mean": mean(2),
        "unknown_share_mean": mean(3),
        "naive_off_by_0_1": sum(abs(r[1] - r[0]) > 0.1 for r in rows) / n,
        "honest_off_by_0_1": sum(abs(r[2] - r[0]) > 0.1 for r in rows) / n,
    }


def cohort_af(samples, truth, gq_min):
    """samples: [(дорожка GQ, {ключ: копии})]; truth: {ключ: копии}. AF двумя способами по
    эталонным вариантам, у которых в когорте есть хотя бы один PASS-вызов (иначе сайта нет и в базе).

    AN = 2N: в AC все PASS-вызовы, в AN все образцы. AN по известным: генотип образца известен,
    если запись gVCF в позиции (блок или сам вызов) имеет GQ ≥ gq_min, как фильтр adj в gnomAD;
    неизвестный генотип не входит ни в AC, ни в AN."""
    het, hom, no_known = [], [], 0
    n = len(samples)
    for key, copies in truth.items():
        chrom, pos = key[0], key[1]
        ac_all = ac = known = 0
        for track, calls in samples:
            ac_all += calls.get(key, 0)
            t = track.get(chrom)
            if t is not None and pos < len(t) and t[pos] >= gq_min:
                known += 1
                ac += calls.get(key, 0)
        if ac_all == 0:
            continue
        if known == 0:
            no_known += 1
            continue
        row = (copies / 2.0, ac_all / (2.0 * n), ac / (2.0 * known), 1 - known / float(n))
        (hom if copies == 2 else het).append(row)
    return {"samples": n, "het": af_summary(het), "hom": af_summary(hom), "sites_without_known": no_known}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("series")
    p.add_argument("--bed", default="data/truth/giab_v5.0q.bed")
    p.add_argument("--truth", default="data/truth/giab_v5.0q.vcf.gz")
    p.add_argument("--strata", default="data/strat")
    p.add_argument("--ref", default="data/ref/ref.fa")
    p.add_argument("--gq", type=int, default=20)
    p.add_argument("--json")
    p.add_argument("--md")
    a = p.parse_args(argv)
    bed = read_bed(a.bed)
    strata_files = read_strata(a.strata) if a.strata else {}
    strata = {n: read_bed(strata_files[n]) for n in ("all_difficult", "not_in_all_difficult") if n in strata_files}
    truth_sites = [
        (r["chrom"], r["pos"])
        for r in read_vcf(a.truth)
        if gt_alleles(r["gt"]) not in (None, (0, 0)) and in_bed(bed, r["chrom"], r["pos"])
    ]
    dirs = sorted(
        (os.path.join(a.series, d) for d in os.listdir(a.series) if POINT.match(d)),
        key=lambda d: -float(POINT.match(os.path.basename(d)).group(1)),
    )
    dirs = [d for d in dirs if os.path.exists(os.path.join(d, GVCF))]
    points = [point(d, bed, strata, truth_sites, a.gq) for d in dirs]
    res = {"gq_min": a.gq, "points": points, "cohorts": {}}
    seqs = read_fasta(a.ref)
    truth = {
        k: gt.count(1)
        for k, gt in keyed(
            [r for r in read_vcf(a.truth) if gt_alleles(r["gt"]) not in (None, (0, 0))], seqs, bed
        ).items()
    }
    samples = {d: (gq_track(os.path.join(d, GVCF)), called_keys(os.path.join(d, VCF), seqs, bed)) for d in dirs}
    for name, min_depth in COHORTS:
        chosen = [d for d, q in zip(dirs, points) if q["mean_depth"] >= min_depth]
        if not chosen:
            continue
        res["cohorts"][name] = dict(
            cohort_af([samples[d] for d in chosen], truth, a.gq),
            depths=[q["mean_depth"] for q in points if q["mean_depth"] >= min_depth],
        )
    md = [
        "# Уверенный генотип по gVCF и глубина\n",
        "DeepVariant, gVCF, GQ ≥ %d; доверенные участки GIAB v5.0q. «Эталонные варианты» — позиции вариантов "
        "эталона, где генотип образца известен с этой уверенностью.\n" % a.gq,
        "| глубина | все позиции | вне сложных участков | в сложных участках | эталонные варианты |",
        "|---|---|---|---|---|",
    ]
    for q in points:
        md.append(
            "| %.1fx | %.1f %% | %.1f %% | %.1f %% | %.1f %% |"
            % (
                q["mean_depth"],
                100 * q["bases_confident"],
                100 * q.get("bases_confident_not_in_all_difficult", float("nan")),
                100 * q.get("bases_confident_all_difficult", float("nan")),
                100 * q["truth_sites_confident"],
            )
        )
    md.append("")
    top = points[0] if points else {}
    if "truth_sites_low_difficult" in top:
        md.append(
            "На %.1fx GQ < %d у %d позиций эталонных вариантов из %d; %d из них — в сложных участках GIAB, где "
            "лежат %d эталонных вариантов из %d.\n"
            % (
                top["mean_depth"],
                a.gq,
                top["truth_sites_low"],
                top["truth_sites"],
                top["truth_sites_low_difficult"],
                top["truth_sites_difficult"],
                top["truth_sites"],
            )
        )
    md.append("## Когорта из копий одного генома\n")
    md.append(
        "Точки серии — копии HG002 на разной глубине, правильная AF известна. Эталонные варианты v5.0q, у "
        "которых в когорте есть хотя бы один носитель. «AN = 2N» — образец без данных засчитан гомозиготой "
        "по референсу; «AN по известным» — генотип образца известен, если запись gVCF в позиции (блок или "
        "вызов) имеет GQ ≥ %d, неизвестный не входит ни в AC, ни в AN.\n" % a.gq
    )
    md.append(
        "| когорта | генотип | вариантов | правильная AF | AF при AN = 2N | AF при AN по известным | "
        "доля неизвестных | ошибка AF > 0,1: AN = 2N | ошибка AF > 0,1: AN по известным |"
    )
    md.append("|---|---|---|---|---|---|---|---|---|")
    for c in res["cohorts"].values():
        label = "%d образцов, %.1f–%.1fx" % (c["samples"], min(c["depths"]), max(c["depths"]))
        for g, gl in (("het", "гетерозигота"), ("hom", "гомозигота")):
            e = c[g]
            if not e["sites"]:
                continue
            md.append(
                "| %s | %s | %d | %.2f | %.3f | %.3f | %.1f %% | %.1f %% | %.1f %% |"
                % (
                    label,
                    gl,
                    e["sites"],
                    e["truth_af"],
                    e["naive_af_mean"],
                    e["honest_af_mean"],
                    100 * e["unknown_share_mean"],
                    100 * e["naive_off_by_0_1"],
                    100 * e["honest_off_by_0_1"],
                )
            )
    md.append("")
    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(res, fh, indent=2, sort_keys=True)
            fh.write("\n")
    if a.md:
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write("\n".join(md))
    if not (a.json or a.md):
        sys.stdout.write("\n".join(md))
    return 0


if __name__ == "__main__":
    sys.exit(main())
