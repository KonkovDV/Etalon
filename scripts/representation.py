#!/usr/bin/env python3
"""Один вариант — разная запись: сколько «различных» вариантов дают несколько вызывателей.

    python3 scripts/representation.py --ref data/ref/ref.fa --bed data/truth/giab_v5.0q.bed \\
        --pairs OUT/pairs --json OUT/representation.json --md OUT/representation.md \\
        bcftools=OUT/bcftools.pass.vcf.gz strelka2=OUT/strelka2.pass.vcf.gz deepvariant=OUT/deepvariant.pass.vcf.gz

В базе частот вариант — это ключ (CHROM, POS, REF, ALT). Ключи считаются на трёх уровнях:

  * как есть        — запись VCF как её выдала программа (мультиаллельная запись — один ключ);
  * разбиение       — по ключу на каждый ALT, общие основания обрезаны (bcftools norm -m -any без -f);
  * нормализация    — разбиение и сдвиг инделов влево по референсу (bcftools norm -m -any -f ref).

Попарное сравнение hap.py (scripts/compare_representation.sh) отвечает на вопрос, который
ключи не решают: тот же ли это гаплотип. Если hap.py засчитал вариант как TP, а его
нормализованного ключа у второй программы нет, значит, вторая программа записала тот же
гаплотип иначе (обычно делинс против SNV рядом с инделом или разное разложение в повторе).
Такие ключи — ложные «уникальные» варианты, которые нормализация не убирает.

Примеры и классы расхождений берутся по суперлокусам hap.py: внутри суперлокуса гаплотипы
сравниваются целиком, поэтому туда попадают все записи события, даже если они в 20 п.н. друг
от друга. Для каждого такого суперлокуса гаплотипы собираются заново из референса перебором
фаз, независимо от hap.py: совпадение должно получиться и без него.

Учитываются PASS-вызовы с ненулевым генотипом внутри доверенных участков (первое основание REF).
"""

import argparse
import gzip
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from concordance import (  # noqa: E402
    gt_alleles,
    in_bed,
    keyed,
    left_normalize,
    read_bed,
    read_fasta,
    read_vcf,
)

LEVELS = (("raw", "как есть"), ("split", "разбиение"), ("norm", "нормализация"))
CONTIG = re.compile(r"^(chr[0-9XYM]+)_(\d+)_(\d+)$")
MAX_HETS = 12  # гетерозиготных записей одной стороны в суперлокусе: 2^12 вариантов фазы
FLANK = 6  # п.н. референса по краям примера: чтобы повтор было видно целиком


def called(records):
    return [r for r in records if gt_alleles(r["gt"]) not in (None, (0, 0))]


def raw_keys(records, bed):
    out = {}
    for r in records:
        if in_bed(bed, r["chrom"], r["pos"]):
            out[(r["chrom"], r["pos"], r["ref"], ",".join(r["alts"]))] = gt_alleles(r["gt"])
    return out


def caller_keys(path, seqs, bed):
    recs = called(read_vcf(path))
    return {
        "raw": raw_keys(recs, bed),
        "split": keyed(recs, seqs, bed, left_align=False),
        "norm": keyed(recs, seqs, bed, left_align=True),
    }


def happy_rows(path, with_superlocus=False):
    """Строки размеченного VCF hap.py: (chrom, pos, ref, alts, {TRUTH: fmt, QUERY: fmt}[, BS])."""
    samples = None
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as fh:
        for line in fh:
            if line.startswith("##"):
                continue
            f = line.rstrip("\n").split("\t")
            if line.startswith("#"):
                samples = f[9:]
                continue
            keys = f[8].split(":")
            fmt = {s: dict(zip(keys, v.split(":"))) for s, v in zip(samples, f[9:])}
            row = (f[0], int(f[1]), f[3].upper(), [a.upper() for a in f[4].split(",")], fmt)
            if with_superlocus:
                m = re.search(r"(?:^|;)BS=(\d+)", f[7])
                row += (int(m.group(1)) if m else int(f[1]),)
            yield row


def matched_keys(path, seqs, bed, sample):
    """Нормализованные ключи вариантов, которые hap.py засчитал (BD=TP) у образца sample."""
    out = set()
    for chrom, pos, ref, alts, fmt in happy_rows(path):
        s = fmt.get(sample, {})
        if s.get("BD") != "TP":
            continue
        gt = gt_alleles(s.get("GT", "."))
        for i in sorted(set(gt or ())):
            if i == 0 or i > len(alts) or alts[i - 1] in ("*", "."):
                continue
            p, r, a = left_normalize(pos, ref, alts[i - 1], seqs[chrom])
            if in_bed(bed, chrom, p):
                out.add((chrom, p, r, a))
    return out


def decisions(path):
    """Счётчики hap.py по размеченному VCF: FN эталона, FP запроса, из них расхождение генотипа."""
    fn = fp = gt_only = 0
    for _, _, _, _, fmt in happy_rows(path):
        t, q = fmt.get("TRUTH", {}), fmt.get("QUERY", {})
        fn += t.get("BD") == "FN"
        if q.get("BD") == "FP":
            fp += 1
            gt_only += q.get("BK") == "am"  # аллели совпали, генотип нет
    return {"fn": fn, "fp": fp, "fp_genotype_only": gt_only}


def shape(key):
    _, _, r, a = key
    if len(r) == len(a) == 1:
        return "snv"
    if len(r) == len(a):
        return "mnp"
    return "indel" if r[0] == a[0] else "delins"


def kind(mine, theirs):
    """Класс расхождения по форме нормализованных ключей двух программ в одном суперлокусе.

    После нормализации простой индел начинается с общего «якорного» основания; делинс —
    разные длины без общего первого основания; MNP — замена нескольких оснований подряд."""
    a, b = {shape(k) for k in mine}, {shape(k) for k in theirs}
    subs = {"snv", "mnp"}
    if not a or not b:
        return "лишняя запись"
    if "delins" in a | b:
        return "делинс против нескольких записей"
    if a <= subs and b <= subs:
        return "замена нескольких оснований: одна запись против нескольких"
    if a <= subs or b <= subs:
        return "замены против инделов"
    return "инделы разложены по-разному"


def grch38(chrom, pos):
    m = CONTIG.match(chrom)
    return ("%s:%d" % (m.group(1), pos + int(m.group(2)) - 1)) if m else "%s:%d" % (chrom, pos)


def apply_alleles(seq, start, end, alleles):
    """Последовательность окна [start, end] (1-based) с аллелями одного гаплотипа; None, если аллели
    перекрываются или REF не совпал с референсом."""
    out, cur = [], start
    for pos, ref, alt in sorted(alleles):
        if pos < cur or seq[pos - 1 : pos - 1 + len(ref)] != ref:
            return None
        out.append(seq[cur - 1 : pos - 1])
        out.append(alt)
        cur = pos + len(ref)
    out.append(seq[cur - 1 : end])
    return "".join(out)


def haplotype_pairs(calls, seq, start, end):
    """Все пары гаплотипов окна, которые дают вызовы одной стороны при какой-нибудь фазе.

    calls — [(pos, ref, alts, (i, j))]. Фаза из VCF не используется (её не использует и hap.py):
    перебираются все расстановки гетерозигот по двум гаплотипам. None — слишком много гетерозигот."""
    hets = [n for n, c in enumerate(calls) if c[3][0] != c[3][1]]
    if len(hets) > MAX_HETS:
        return None
    pairs = set()
    for mask in range(1 << max(0, len(hets) - 1)):  # первая гетерозигота фиксирована: пары неупорядочены
        flip = {n: (mask >> b) & 1 for b, n in enumerate(hets[1:])}
        haps = ([], [])
        for n, (pos, ref, alts, (i, j)) in enumerate(calls):
            for h, allele in enumerate((j, i) if flip.get(n) else (i, j)):
                if allele and alts[allele - 1] not in ("*", "."):
                    haps[h].append((pos, ref, alts[allele - 1]))
        seqs = [apply_alleles(seq, start, end, h) for h in haps]
        if None not in seqs:
            pairs.add(tuple(sorted(seqs)))
    return pairs


def compress(seq, min_run=4):
    """Короткие тандемные повторы в скобках: GCTCTCTCTAC -> G(CT)4AC. Единица 1–4 п.н., повтор
    не короче min_run оснований и не меньше трёх копий (для гомополимера — min_run копий)."""
    out, i = [], 0
    while i < len(seq):
        best = (1, 1)  # (длина единицы, копий)
        for unit in range(1, 5):
            n = 1
            while seq[i + n * unit : i + (n + 1) * unit] == seq[i : i + unit] and i + (n + 1) * unit <= len(seq):
                n += 1
            if n * unit >= min_run and n >= (min_run if unit == 1 else 3) and n * unit > best[0] * best[1]:
                best = (unit, n)
        unit, n = best
        if n > 1:
            out.append("(%s)%d" % (seq[i : i + unit], n))
            i += unit * n
        else:
            out.append(seq[i])
            i += 1
    return "".join(out)


def side_calls(rows, sample):
    """Вызовы одной стороны суперлокуса и засчитаны ли все они hap.py (BD=TP)."""
    calls, all_tp = [], True
    for _, pos, ref, alts, fmt, _ in rows:
        s = fmt.get(sample, {})
        gt = gt_alleles(s.get("GT", "."))
        if gt in (None, (0, 0)):
            continue
        all_tp = all_tp and s.get("BD") == "TP"
        calls.append((pos, ref, alts, gt))
    return calls, all_tp


def norm_keys(calls, chrom, seq):
    """{нормализованный ключ: число копий аллели в генотипе (1 или 2)}."""
    out = {}
    for pos, ref, alts, gt in calls:
        for i in sorted(set(gt)):
            if i and alts[i - 1] not in ("*", "."):
                p, r, a = left_normalize(pos, ref, alts[i - 1], seq)
                out[(chrom, p, r, a)] = gt.count(i)
    return out


def same_haplotype_loci(vcf, seqs, bed):
    """Суперлокусы hap.py, где обе стороны засчитаны целиком, а нормализованные ключи различаются.

    Для каждого гаплотипы собираются заново (haplotype_pairs): verified — нашлась фаза, при
    которой обе записи дают одну и ту же пару гаплотипов."""
    loci = {}
    for row in happy_rows(vcf, with_superlocus=True):
        loci.setdefault((row[0], row[5]), []).append(row)
    out = []
    for (chrom, _), rows in sorted(loci.items()):
        a_calls, a_tp = side_calls(rows, "TRUTH")
        b_calls, b_tp = side_calls(rows, "QUERY")
        if not (a_calls and b_calls and a_tp and b_tp):
            continue
        seq = seqs[chrom]
        ka, kb = norm_keys(a_calls, chrom, seq), norm_keys(b_calls, chrom, seq)
        only_a, only_b = sorted(set(ka) - set(kb)), sorted(set(kb) - set(ka))
        if not (only_a or only_b) or not any(in_bed(bed, chrom, k[1]) for k in only_a + only_b):
            continue
        shared = sorted(set(ka) & set(kb))
        calls = a_calls + b_calls
        start = min(c[0] for c in calls)
        end = max(c[0] + len(c[1]) - 1 for c in calls)
        pa, pb = haplotype_pairs(a_calls, seq, start, end), haplotype_pairs(b_calls, seq, start, end)
        common = sorted(pa & pb) if pa is not None and pb is not None else []
        ref_seq = seq[start - 1 : end]
        out.append(
            {
                "chrom": chrom,
                "start": start,
                "end": end,
                "kind": kind(only_a, only_b),
                "a": [(k, ka[k]) for k in only_a],
                "b": [(k, kb[k]) for k in only_b],
                "shared": [(k, ka[k]) for k in shared],
                # общая запись с разным числом копий: список различий тогда не объясняет локус целиком
                "shared_same_gt": all(ka[k] == kb[k] for k in shared),
                "ref": ref_seq,
                "haplotypes": [h for h in common[0] if h != ref_seq] if common else [],
                "verified": bool(common),
            }
        )
    return out


def example(locus, a, b, seq, flank=FLANK):
    """Пример для отчёта: записи обеих программ с генотипом, общие записи суперлокуса, референс
    и собранный гаплотип с фланками (сжатые повторы видно целиком)."""

    def rec(item):
        (chrom, pos, ref, alt), copies = item
        return "%s %s>%s %s" % (grch38(chrom, pos).split(":")[1], ref, alt, "1/1" if copies == 2 else "0/1")

    left = seq[max(0, locus["start"] - 1 - flank) : locus["start"] - 1]
    right = seq[locus["end"] : locus["end"] + flank]
    return {
        "locus": "%s–%s" % (grch38(locus["chrom"], locus["start"]), grch38(locus["chrom"], locus["end"]).split(":")[1]),
        "kind": locus["kind"],
        a: [rec(x) for x in locus["a"]],
        b: [rec(x) for x in locus["b"]],
        "shared": [rec(x) for x in locus["shared"]],
        "ref": compress(left + locus["ref"] + right),
        "haplotypes": [compress(left + h + right) for h in locus["haplotypes"]],
    }


def pick_examples(loci, n):
    """До n проверенных суперлокусов, которые объясняются одним списком различий (общие записи
    с тем же генотипом): сначала по одному на класс, короткие окна раньше длинных."""
    pool = sorted(
        (x for x in loci if x["verified"] and x["shared_same_gt"]), key=lambda x: (x["end"] - x["start"], x["start"])
    )
    chosen, kinds = [], set()
    for x in pool:
        if x["kind"] not in kinds and len(chosen) < n:
            chosen.append(x)
            kinds.add(x["kind"])
    for x in pool:
        if x not in chosen and len(chosen) < n:
            chosen.append(x)
    return sorted(chosen, key=lambda x: x["start"])


def compare_pair(a, b, ka, kb, pair_dir, seqs, bed, examples=3):
    out = {"a": a, "b": b}
    for level, _ in LEVELS:
        sa, sb = set(ka[level]), set(kb[level])
        out[level] = {"shared": len(sa & sb), "only_a": len(sa - sb), "only_b": len(sb - sa)}
    na, nb = set(ka["norm"]), set(kb["norm"])
    out["gt_differs"] = sum(1 for k in na & nb if ka["norm"][k] != kb["norm"][k])
    vcf = os.path.join(pair_dir, "happy.vcf.gz")
    if not os.path.exists(vcf):
        return out
    tp_a = matched_keys(vcf, seqs, bed, "TRUTH")
    tp_b = matched_keys(vcf, seqs, bed, "QUERY")
    rep_a = sorted((na - nb) & tp_a)
    rep_b = sorted((nb - na) & tp_b)
    out.update(decisions(vcf))
    out["same_haplotype_only_a"] = len(rep_a)
    out["same_haplotype_only_b"] = len(rep_b)
    out["real_only_a"] = len(na - nb) - len(rep_a)
    out["real_only_b"] = len(nb - na) - len(rep_b)
    loci = same_haplotype_loci(vcf, seqs, bed)
    kinds = {}
    for x in loci:
        kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
    out["same_haplotype_loci"] = len(loci)
    out["same_haplotype_loci_verified"] = sum(x["verified"] for x in loci)
    out["loci"] = [
        {"chrom": x["chrom"], "start": x["start"], "end": x["end"], "kind": x["kind"], "verified": x["verified"]}
        for x in loci
    ]
    ex = [example(x, a, b, seqs[x["chrom"]]) for x in pick_examples(loci, examples)]
    raw = out["raw"]["only_a"] + out["raw"]["only_b"]
    split = out["split"]["only_a"] + out["split"]["only_b"]
    norm = out["norm"]["only_a"] + out["norm"]["only_b"]
    same = out["same_haplotype_only_a"] + out["same_haplotype_only_b"]
    out["breakdown"] = {
        "raw_discordant": raw,
        "removed_by_split": raw - split,
        "removed_by_left_shift": split - norm,
        "same_haplotype": same,
        "real": norm - same,
        "representation_share": (raw - (norm - same)) / raw if raw else None,
    }
    out["kinds"] = kinds
    out["examples"] = ex
    return out


def distinct_loci(pairs, difficult=None):
    """Разные локусы «тот же гаплотип» по всем парам: в каких парах встретились и лежат ли
    в сложных участках GIAB (all_difficult)."""
    out = {}
    for p in pairs:
        for x in p.get("loci", []):
            key = (x["chrom"], x["start"], x["end"])
            e = out.setdefault(
                key,
                {
                    "locus": "%s–%s" % (grch38(x["chrom"], x["start"]), grch38(x["chrom"], x["end"]).split(":")[1]),
                    "pairs": [],
                    "verified": True,
                },
            )
            e["pairs"].append("%s/%s" % (p["a"], p["b"]))
            e["verified"] = e["verified"] and x["verified"]
            if difficult is not None:
                e["in_difficult"] = any(in_bed(difficult, x["chrom"], q) for q in range(x["start"], x["end"] + 1))
    return [out[k] for k in sorted(out)]


def build(calls, ref, bed_path, pairs_dir, difficult_bed=None):
    seqs = read_fasta(ref)
    bed = read_bed(bed_path)
    keys = {name: caller_keys(path, seqs, bed) for name, path in calls.items()}
    names = list(calls)
    res = {"callers": {}, "union": {}, "pairs": []}
    for name in names:
        res["callers"][name] = {level: len(keys[name][level]) for level, _ in LEVELS}
    for level, _ in LEVELS:
        res["union"][level] = len(set().union(*(keys[n][level] for n in names)))
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            res["pairs"].append(
                compare_pair(a, b, keys[a], keys[b], os.path.join(pairs_dir or "", "%s_vs_%s" % (a, b)), seqs, bed)
            )
    rep = sum(p.get("same_haplotype_only_a", 0) + p.get("same_haplotype_only_b", 0) for p in res["pairs"])
    res["same_haplotype_keys_total"] = rep
    res["loci"] = distinct_loci(res["pairs"], read_bed(difficult_bed) if difficult_bed else None)
    return res


def render_md(res):
    names = list(res["callers"])
    md = ["# Один вариант — разная запись\n"]
    md.append(
        "PASS-вызовы с ненулевым генотипом в доверенных участках GIAB v5.0q. Ключ варианта — "
        "(CHROM, POS, REF, ALT), как в базе частот.\n"
    )
    md.append("## Сколько различных вариантов\n")
    md.append("| уровень | " + " | ".join(names) + " | объединение |")
    md.append("|---|" + "---|" * (len(names) + 1))
    for level, label in LEVELS:
        md.append(
            "| %s | %s | %d |" % (label, " | ".join(str(res["callers"][n][level]) for n in names), res["union"][level])
        )
    md.append("")
    md.append("## Попарно\n")
    md.append(
        "| пара | только у первой / второй: как есть | после разбиения | после нормализации | "
        "из них тот же гаплотип | реальные различия | разный генотип при том же ключе |"
    )
    md.append("|---|---|---|---|---|---|---|")
    for p in res["pairs"]:
        md.append(
            "| %s / %s | %d / %d | %d / %d | %d / %d | %s / %s | %s / %s | %d |"
            % (
                p["a"],
                p["b"],
                p["raw"]["only_a"],
                p["raw"]["only_b"],
                p["split"]["only_a"],
                p["split"]["only_b"],
                p["norm"]["only_a"],
                p["norm"]["only_b"],
                p.get("same_haplotype_only_a", "–"),
                p.get("same_haplotype_only_b", "–"),
                p.get("real_only_a", "–"),
                p.get("real_only_b", "–"),
                p["gt_differs"],
            )
        )
    md.append("")
    if all("breakdown" in p for p in res["pairs"]):
        md.append("## Из чего складываются «различия»\n")
        md.append(
            "| пара | различных ключей как есть | убрало разбиение | убрал сдвиг влево | тот же гаплотип "
            "(суперлокусов) | реальные различия | доля записи |"
        )
        md.append("|---|---|---|---|---|---|---|")
        for p in res["pairs"]:
            d = p["breakdown"]
            md.append(
                "| %s / %s | %d | %d | %d | %d (%d) | %d | %.0f %% |"
                % (
                    p["a"],
                    p["b"],
                    d["raw_discordant"],
                    d["removed_by_split"],
                    d["removed_by_left_shift"],
                    d["same_haplotype"],
                    p.get("same_haplotype_loci", 0),
                    d["real"],
                    100 * d["representation_share"],
                )
            )
        md.append("")
    ex = [(p, e) for p in res["pairs"] for e in p.get("examples", [])]
    if ex:
        md.append("## Примеры: тот же гаплотип, другая запись\n")
        md.append(
            "Гаплотипы собраны заново из референса перебором фаз, без hap.py. Повторы сжаты: (CT)8 — восемь "
            "копий CT; по краям по %d п.н. референса.\n" % FLANK
        )
        md.append("| локус (GRCh38) | что | первая программа | вторая программа | общие записи | референс → гаплотип |")
        md.append("|---|---|---|---|---|---|")
        for p, e in ex:
            md.append(
                "| %s | %s | %s: %s | %s: %s | %s | `%s` → `%s` |"
                % (
                    e["locus"],
                    e["kind"],
                    p["a"],
                    "; ".join(e[p["a"]]) or "–",
                    p["b"],
                    "; ".join(e[p["b"]]) or "–",
                    "; ".join(e["shared"]) or "–",
                    e["ref"],
                    "`, `".join(e["haplotypes"]),
                )
            )
        md.append("")
        total = sum(p.get("same_haplotype_loci", 0) for p in res["pairs"])
        ok = sum(p.get("same_haplotype_loci_verified", 0) for p in res["pairs"])
        md.append(
            "Гаплотипы совпали при сборке из референса в %d суперлокусах из %d, которые hap.py засчитал целиком.\n"
            % (ok, total)
        )
    if res.get("loci"):
        md.append("## Все локусы «тот же гаплотип»\n")
        md.append("| локус (GRCh38) | пары | в сложных участках GIAB |")
        md.append("|---|---|---|")
        for x in res["loci"]:
            where = {True: "да", False: "нет"}.get(x.get("in_difficult"), "–")
            md.append("| %s | %s | %s |" % (x["locus"], ", ".join(x["pairs"]), where))
        md.append("")
    return "\n".join(md)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--ref", required=True)
    p.add_argument("--bed", required=True, help="доверенные участки эталона")
    p.add_argument("--pairs", help="каталог с <a>_vs_<b>/happy.vcf.gz")
    p.add_argument("--difficult", help="BED сложных участков GIAB (all_difficult): где лежат локусы")
    p.add_argument("--json")
    p.add_argument("--md")
    p.add_argument("calls", nargs="+", help="name=VCF (только PASS)")
    a = p.parse_args(argv)
    calls = dict(item.split("=", 1) for item in a.calls)
    res = build(calls, a.ref, a.bed, a.pairs, a.difficult)
    md = render_md(res)
    if a.json:
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
