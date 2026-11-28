#!/usr/bin/env python3
"""Метрика согласия генотипов по формуле патента RU 2846268 рядом с GA4GH.

    python3 scripts/concordance.py --truth-dir data/truth --ref data/ref/ref.fa --strata data/strat \\
        [--compare docs/results/callers/compare.json] [--json OUT.json] [--md OUT.md] \\
        bcftools=results/run/HG002.vcf.gz strelka2=results/callers/strelka2/HG002.strelka2.vcf.gz

Формула (патент RU 2846268, формула изобретения):
    F = N(вызовы, совпавшие с эталоном по CHR, POS, REF, ALT и GT) / N(вызовы, совпавшие по CHR, POS, REF, ALT)
    у обоих — только вызовы с FILTER = PASS, GQ > 10 и sum(AD) > 10; порог пригодности F > 99,9 %.

Реализация:
  * literal    — как написано: ключ (CHR, POS, REF, ALT) берётся из VCF как есть;
  * normalized — обе стороны разбиты на двуаллельные записи и нормализованы
                 (обрезка общих оснований и сдвиг влево по референсу, Tan et al. 2015),
                 то же делает `bcftools norm -m -any -f ref`;
  * split_only — только разбиение и обрезка, без сдвига влево: показывает, какая
                 часть разницы literal/normalized приходится на мультиаллельные записи;
  * GQ берётся из FORMAT/GQ; если его нет (bcftools call), GQ = разность двух
    наименьших PL, как в GATK;
  * GT сравнивается без учёта фазы и порядка аллелей;
  * --bed / BED эталона: учитываются эталонные варианты и вызовы, у которых первое
    основание REF лежит в доверенных участках эталона; --strata DIR (strata.tsv)
    дополнительно считает F по стратам GIAB.

Рядом считается, какая доля эталонных вариантов вообще попала в знаменатель F, а с
--compare (выход scripts/compare_callers.py) — recall, precision и F1 hap.py тех же вызовов.
Для F невидимы пропуски (FN) и лишние вызовы (FP): они не входят ни в числитель, ни в знаменатель.

    python3 scripts/concordance.py norm-check REF.fa TSV_DIR VCF ...   # сверка с bcftools norm
"""

import argparse
import bisect
import gzip
import json
import os
import sys

TRUTHS = ("giab_v5.0q", "giab_v4.2.1")
STRATA = ("not_in_all_difficult", "all_difficult", "tandem_repeats", "homopolymers_ge7")


# ----------------------------------------------------------------- VCF


def open_text(path):
    return gzip.open(path, "rt") if path.endswith(".gz") else open(path, encoding="utf-8")


def read_fasta(path):
    seqs, name, chunks = {}, None, []
    with open_text(path) as fh:
        for line in fh:
            line = line.strip()
            if line.startswith(">"):
                if name is not None:
                    seqs[name] = "".join(chunks).upper()
                name, chunks = line[1:].split()[0], []
            elif line:
                chunks.append(line)
    if name is not None:
        seqs[name] = "".join(chunks).upper()
    return seqs


def genotype_quality(fmt):
    gq = fmt.get("GQ", ".")
    if gq not in (".", ""):
        return float(gq)
    pl = sorted(int(x) for x in fmt.get("PL", ".").split(",") if x not in (".", ""))
    if len(pl) < 2:
        return None
    return float(pl[1] - pl[0])


def allele_depth(fmt):
    ad = [int(x) for x in fmt.get("AD", ".").split(",") if x not in (".", "")]
    return sum(ad) if ad else None


def read_vcf(path):
    """Записи первого образца: dict(chrom, pos, ref, alts, filter, gt, gq, ad)."""
    with open_text(path) as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            f = line.rstrip("\n").split("\t")
            fmt = dict(zip(f[8].split(":"), f[9].split(":"))) if len(f) > 9 else {}
            yield {
                "chrom": f[0],
                "pos": int(f[1]),
                "ref": f[3].upper(),
                "alts": [a.upper() for a in f[4].split(",")],
                "filter": f[6],
                "gt": fmt.get("GT", "."),
                "gq": genotype_quality(fmt),
                "ad": allele_depth(fmt),
            }


def gt_alleles(gt):
    """'0|1' -> (0, 1); None для неполного генотипа."""
    parts = gt.replace("|", "/").split("/")
    if not parts or any(p in (".", "") for p in parts):
        return None
    return tuple(sorted(int(p) for p in parts))


# ----------------------------------------------------------------- нормализация


def trim_only(pos, ref, alt):
    """Обрезка общих оснований справа и слева без сдвига по референсу."""
    while len(ref) > 1 and len(alt) > 1 and ref[-1] == alt[-1]:
        ref, alt = ref[:-1], alt[:-1]
    while len(ref) > 1 and len(alt) > 1 and ref[0] == alt[0]:
        ref, alt, pos = ref[1:], alt[1:], pos + 1
    return pos, ref, alt


def left_normalize(pos, ref, alt, seq):
    """Обрезка общих оснований и сдвиг влево (Tan et al., Bioinformatics 2015)."""
    if len(ref) == len(alt) == 1:
        return pos, ref, alt
    changed = True
    while changed:
        changed = False
        if ref and alt and ref[-1] == alt[-1]:
            ref, alt, changed = ref[:-1], alt[:-1], True
        if (not ref or not alt) and pos > 1:
            pos -= 1
            base = seq[pos - 1]
            ref, alt, changed = base + ref, base + alt, True
    while len(ref) > 1 and len(alt) > 1 and ref[0] == alt[0]:
        ref, alt, pos = ref[1:], alt[1:], pos + 1
    return pos, ref, alt


def split_records(rec, seqs=None, left_align=True):
    """Литерально — одна запись с ALT как есть; с seqs — по записи на ALT, нормализованной
    (left_align=False: только разбиение и обрезка, без сдвига влево).

    Генотип при разбиении: выбранный ALT -> 1, остальные ALT -> 0 (как bcftools norm -m -any)."""
    gt = gt_alleles(rec["gt"])
    if seqs is None:
        yield rec["pos"], rec["ref"], ",".join(rec["alts"]), gt
        return
    for i, alt in enumerate(rec["alts"], start=1):
        if alt in ("*", ".") or alt.startswith("<"):
            continue
        sub = None if gt is None else tuple(sorted(1 if a == i else 0 for a in gt))
        if left_align:
            pos, ref, alt_n = left_normalize(rec["pos"], rec["ref"], alt, seqs[rec["chrom"]])
        else:
            pos, ref, alt_n = trim_only(rec["pos"], rec["ref"], alt)
        yield pos, ref, alt_n, sub


# ----------------------------------------------------------------- участки


def read_bed(path):
    by_chrom = {}
    with open_text(path) as fh:
        for line in fh:
            if not line.strip() or line.startswith(("#", "track", "browser")):
                continue
            f = line.split("\t")
            by_chrom.setdefault(f[0], []).append((int(f[1]), int(f[2])))
    out = {}
    for chrom, iv in by_chrom.items():
        iv.sort()
        merged = []
        for s, e in iv:
            if merged and s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        out[chrom] = ([s for s, _ in merged], [e for _, e in merged])
    return out


def in_bed(bed, chrom, pos):
    """pos 1-based; BED полуоткрытый 0-based."""
    if bed is None:
        return True
    if chrom not in bed:
        return False
    starts, ends = bed[chrom]
    i = bisect.bisect_right(starts, pos - 1) - 1
    return i >= 0 and pos - 1 < ends[i]


def read_strata(strata_dir):
    out = {}
    with open(os.path.join(strata_dir, "strata.tsv"), encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                name, fname = line.rstrip("\n").split("\t")[:2]
                out[name] = os.path.join(strata_dir, fname)
    return out


# ----------------------------------------------------------------- метрика


def passes(rec, gq_min, ad_min):
    return (
        rec["filter"] == "PASS"
        and rec["gq"] is not None
        and rec["gq"] > gq_min
        and rec["ad"] is not None
        and rec["ad"] > ad_min
    )


def keyed(records, seqs, chrom_bed, regions=(), left_align=True):
    """{(chrom, pos, ref, alt): gt} для записей внутри BED эталона и каждого из regions."""
    out = {}
    for rec in records:
        for pos, ref, alt, gt in split_records(rec, seqs, left_align):
            if not in_bed(chrom_bed, rec["chrom"], pos):
                continue
            if any(not in_bed(r, rec["chrom"], pos) for r in regions):
                continue
            out[(rec["chrom"], pos, ref, alt)] = gt
    return out


def patent_f(query, truth, seqs=None, bed=None, regions=(), gq_min=10, ad_min=10, left_align=True):
    """query, truth — списки записей read_vcf. Возвращает числитель, знаменатель и F."""
    q_recs = [r for r in query if passes(r, gq_min, ad_min)]
    t_recs = [r for r in truth if gt_alleles(r["gt"]) not in (None, (0, 0))]
    q = keyed(q_recs, seqs, bed, regions, left_align)
    t = keyed(t_recs, seqs, bed, regions, left_align)
    matched = [k for k in q if k in t]
    num = sum(1 for k in matched if q[k] is not None and q[k] == t[k])
    den = len(matched)
    return {
        "numerator": num,
        "denominator": den,
        "f": num / den if den else None,
        "truth_total": len(t),
        "truth_in_denominator_share": den / len(t) if t else None,
        "query_passing_filters": len(q),
        "query_without_exact_match": len(q) - den,
        "truth_multiallelic": sum(1 for r in t_recs if len(r["alts"]) > 1 and in_bed(bed, r["chrom"], r["pos"])),
        "query_multiallelic": sum(1 for r in q_recs if len(r["alts"]) > 1 and in_bed(bed, r["chrom"], r["pos"])),
    }


def evaluate(calls, truth_dir, ref=None, strata_dir=None, gq_min=10, ad_min=10):
    """calls: {name: vcf}. Результат: {truth: {name: {mode: {...}, "strata": {...}}}}."""
    seqs = read_fasta(ref) if ref else None
    strata = read_strata(strata_dir) if strata_dir else {}
    out = {}
    for truth in TRUTHS:
        vcf = os.path.join(truth_dir, truth + ".vcf.gz")
        bed_path = os.path.join(truth_dir, truth + ".bed")
        if not os.path.exists(vcf):
            continue
        truth_recs = list(read_vcf(vcf))
        bed = read_bed(bed_path)
        out[truth] = {}
        for name, path in calls.items():
            query = list(read_vcf(path))
            entry = {"literal": patent_f(query, truth_recs, None, bed, (), gq_min, ad_min)}
            if seqs:
                entry["normalized"] = patent_f(query, truth_recs, seqs, bed, (), gq_min, ad_min)
                entry["split_only"] = patent_f(query, truth_recs, seqs, bed, (), gq_min, ad_min, left_align=False)
                entry["strata"] = {
                    s: patent_f(query, truth_recs, seqs, bed, (read_bed(strata[s]),), gq_min, ad_min)
                    for s in STRATA
                    if s in strata
                }
            out[truth][name] = entry
    return out


# ----------------------------------------------------------------- вывод


def pct(x, d=3):
    return "—" if x is None else ("%." + str(d) + "f") % (100 * x)


def render_md(res, happy=None, gq_min=10, ad_min=10):
    lines = ["# Метрика патента RU 2846268 рядом с GA4GH", ""]
    lines.append(
        "F — доля совпавших генотипов среди вызовов, точно совпавших с эталоном по CHR, POS, REF, ALT "
        "(PASS, GQ > %d, sum(AD) > %d), внутри доверенных участков эталона. Порог патента — F > 99,9 %%. "
        "Recall, precision и F1 — hap.py (GA4GH) на тех же PASS-вызовах." % (gq_min, ad_min)
    )
    for truth, by_caller in res.items():
        lines += ["", "## %s" % truth, ""]
        lines.append(
            "| Вызыватель | F, % (как в патенте) | F, % (после нормализации) | "
            "Эталонных вариантов в знаменателе F | SNV F1 | Инделы F1 | FN | FP |"
        )
        lines.append("|---|---|---|---|---|---|---|---|")
        for name, e in by_caller.items():
            lit, norm = e["literal"], e.get("normalized", {})
            h = (happy or {}).get("benchmark", {}).get(truth, {}).get(name)
            snp = indel = fn = fp = "—"
            if h:
                snp, indel = "%.4f" % h["SNP"]["f1"], "%.4f" % h["INDEL"]["f1"]
                fn, fp = str(h["SNP"]["fn"] + h["INDEL"]["fn"]), str(h["SNP"]["fp"] + h["INDEL"]["fp"])
            lines.append(
                "| %s | %s (%d/%d) | %s (%d/%d) | %s %% (%d из %d) | %s | %s | %s | %s |"
                % (
                    name,
                    pct(lit["f"]),
                    lit["numerator"],
                    lit["denominator"],
                    pct(norm.get("f")),
                    norm.get("numerator", 0),
                    norm.get("denominator", 0),
                    pct(norm.get("truth_in_denominator_share", lit["truth_in_denominator_share"]), 1),
                    norm.get("denominator", lit["denominator"]),
                    norm.get("truth_total", lit["truth_total"]),
                    snp,
                    indel,
                    fn,
                    fp,
                )
            )
        strata = [n for n in STRATA if any(n in e.get("strata", {}) for e in by_caller.values())]
        if strata:
            lines += ["", "F после нормализации по стратам GIAB (в скобках — числитель/знаменатель):", ""]
            lines.append("| Страта | " + " | ".join(by_caller) + " |")
            lines.append("|---|" + "---|" * len(by_caller))
            for s in strata:
                vals = []
                for e in by_caller.values():
                    r = e.get("strata", {}).get(s)
                    vals.append("—" if not r else "%s (%d/%d)" % (pct(r["f"]), r["numerator"], r["denominator"]))
                lines.append("| %s | %s |" % (s, " | ".join(vals)))
    return "\n".join(lines) + "\n"


def norm_check(ref, tsv_dir, vcfs):
    """Сравнить нормализацию split_records с `bcftools norm -m -any -f ref` (TSV из check_normalization.sh)."""
    seqs = read_fasta(ref)
    rows = []
    for path in vcfs:
        name = os.path.basename(path)[: -len(".vcf.gz")] if path.endswith(".vcf.gz") else os.path.basename(path)
        mine = {(r["chrom"],) + tuple(x) for r in read_vcf(path) for x in split_records(r, seqs)}
        theirs = set()
        with open(os.path.join(tsv_dir, name + ".bcftools.tsv"), encoding="utf-8") as fh:
            for line in fh:
                chrom, pos, ref_a, alt, gt = line.rstrip("\n").split("\t")
                if alt in ("*", ".") or alt.startswith("<"):
                    continue
                theirs.add((chrom, int(pos), ref_a.upper(), alt.upper(), gt_alleles(gt)))
        rows.append((os.path.basename(path), len(theirs), len(mine - theirs), len(theirs - mine)))
    lines = [
        "# Нормализация concordance.py против bcftools norm",
        "",
        "`scripts/check_normalization.sh`: каждый VCF нормализован дважды — `bcftools norm -m -any -f ref` "
        "в образе tools и функцией `split_records` из `scripts/concordance.py`; сравниваются наборы "
        "(CHROM, POS, REF, ALT, GT без фазы). Символьные аллели (`*`, `<...>`) не учитываются.",
        "",
        "| VCF | записей у bcftools norm | только concordance.py | только bcftools norm |",
        "|---|---|---|---|",
    ]
    lines += ["| %s | %d | %d | %d |" % r for r in rows]
    total, diff = sum(r[1] for r in rows), sum(r[2] + r[3] for r in rows)
    lines += ["", "Итог: %d записей, расхождений %d." % (total, diff)]
    return "\n".join(lines) + "\n", diff


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("calls", nargs="+", help="name=VCF")
    p.add_argument("--truth-dir", required=True, help="directory with <truth>.vcf.gz and <truth>.bed")
    p.add_argument("--ref", help="reference FASTA: enables the normalized variant")
    p.add_argument("--strata", help="stratification directory with strata.tsv")
    p.add_argument("--compare", help="compare.json of scripts/compare_callers.py, for the GA4GH columns")
    p.add_argument("--gq", type=float, default=10, help="GQ must be greater than this (patent: 10)")
    p.add_argument("--ad", type=int, default=10, help="sum(AD) must be greater than this (patent: 10)")
    p.add_argument("--json", help="write results as JSON")
    p.add_argument("--md", help="write results as Markdown")
    return p.parse_args(argv)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["norm-check"]:
        if len(argv) < 4:
            sys.stderr.write("usage: concordance.py norm-check REF.fa TSV_DIR VCF [VCF ...]\n")
            return 2
        md, diff = norm_check(argv[1], argv[2], argv[3:])
        sys.stdout.write(md)
        return 1 if diff else 0
    a = parse_args(argv)
    calls = {}
    for item in a.calls:
        name, sep, path = item.partition("=")
        if not sep or not os.path.exists(path):
            sys.stderr.write("expected name=VCF with an existing file: %s\n" % item)
            return 2
        calls[name] = path
    res = evaluate(calls, a.truth_dir, a.ref, a.strata, a.gq, a.ad)
    happy = None
    if a.compare:
        with open(a.compare, encoding="utf-8") as fh:
            happy = json.load(fh)
    md = render_md(res, happy, a.gq, a.ad)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as fh:
            json.dump(
                {"gq_min": a.gq, "ad_min": a.ad, "results": res}, fh, indent=2, sort_keys=True, ensure_ascii=False
            )
            fh.write("\n")
    if a.md:
        with open(a.md, "w", encoding="utf-8") as fh:
            fh.write(md)
    if not (a.json or a.md):
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
