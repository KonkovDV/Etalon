#!/usr/bin/env python3
"""Move VCF/BED records between GRCh38 and the mini-reference contig.

The mini-reference is one region of GRCh38 cut out as its own contig, e.g.
chr20:10,000,001-12,000,000 -> contig "chr20_10000001_12000000" of length
2,000,000. A variant at chr20:10,000,123 sits at position 123 of the contig, so

    new_pos = old_pos - shift,   shift = region_start - 1 = 10,000,000

The same tool runs the other way (`--shift -10000000`) to put calls back on
GRCh38 for annotation or viewing in IGV.

VCF (text in, text out; .gz input is read transparently):
  * only records with CHROM == --from-contig and the whole REF allele inside
    [--keep-start, --keep-end] (1-based, inclusive, input coordinates) are kept;
    a deletion that runs past the region end would point outside the contig;
  * all ##contig header lines are replaced by one line for --to-contig;
  * a ##shift_coords line records what was done (provenance).

BED (0-based, half-open):
  * intervals are clipped to [--keep-start - 1, --keep-end) and then shifted;
  * empty intervals after clipping are dropped.

The script is deliberately stdlib-only: it runs inside the tools image.
"""

import argparse
import contextlib
import gzip
import io
import sys


def _open_text(path):
    if path == "-":
        return io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8")
    if path.endswith(".gz") or path.endswith(".bgz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return open(path, "rt", encoding="utf-8")


def shift_vcf(lines, out, from_contig, to_contig, to_length, shift, keep_start, keep_end):
    kept = dropped = 0
    for line in lines:
        if line.startswith("##contig="):
            continue
        if line.startswith("#CHROM"):
            out.write("##contig=<ID=%s,length=%d>\n" % (to_contig, to_length))
            out.write(
                "##shift_coords=<from=%s,to=%s,shift=%d,keep=%d-%d>\n"
                % (from_contig, to_contig, shift, keep_start, keep_end)
            )
            out.write(line)
            continue
        if line.startswith("#"):
            out.write(line)
            continue
        fields = line.rstrip("\n").split("\t")
        if fields[0] != from_contig:
            dropped += 1
            continue
        pos = int(fields[1])
        ref_end = pos + len(fields[3]) - 1
        if pos < keep_start or ref_end > keep_end:
            dropped += 1
            continue
        fields[0] = to_contig
        fields[1] = str(pos - shift)
        out.write("\t".join(fields) + "\n")
        kept += 1
    return kept, dropped


def shift_bed(lines, out, from_contig, to_contig, shift, keep_start, keep_end):
    lo, hi = keep_start - 1, keep_end  # region as 0-based half-open
    kept = dropped = 0
    for line in lines:
        if not line.strip() or line.startswith(("#", "track", "browser")):
            continue
        fields = line.rstrip("\n").split("\t")
        if fields[0] != from_contig:
            dropped += 1
            continue
        start, end = max(int(fields[1]), lo), min(int(fields[2]), hi)
        if start >= end:
            dropped += 1
            continue
        fields[0], fields[1], fields[2] = to_contig, str(start - shift), str(end - shift)
        out.write("\t".join(fields[:3]) + "\n")
        kept += 1
    return kept, dropped


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("mode", choices=("vcf", "bed"))
    p.add_argument("input", help="input file or '-' for stdin")
    p.add_argument("--from-contig", required=True)
    p.add_argument("--to-contig", required=True)
    p.add_argument("--shift", type=int, required=True, help="subtracted from every coordinate (negative = shift right)")
    p.add_argument("--keep-start", type=int, required=True, help="1-based first kept base, input coordinates")
    p.add_argument("--keep-end", type=int, required=True, help="1-based last kept base, input coordinates")
    p.add_argument("--to-length", type=int, help="length of --to-contig for the VCF header (VCF mode)")
    p.add_argument("-o", "--output", default="-")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.keep_start < 1 or args.keep_end < args.keep_start:
        sys.exit("error: need 1 <= --keep-start <= --keep-end")
    if args.mode == "vcf" and not args.to_length:
        sys.exit("error: --to-length is required in vcf mode")
    with contextlib.ExitStack() as stack:
        fh = stack.enter_context(_open_text(args.input))
        out = sys.stdout if args.output == "-" else stack.enter_context(open(args.output, "w", encoding="utf-8"))
        if args.mode == "vcf":
            kept, dropped = shift_vcf(
                fh, out, args.from_contig, args.to_contig, args.to_length, args.shift, args.keep_start, args.keep_end
            )
        else:
            kept, dropped = shift_bed(
                fh, out, args.from_contig, args.to_contig, args.shift, args.keep_start, args.keep_end
            )
    sys.stderr.write("[shift_coords] %s: kept %d, dropped %d\n" % (args.mode, kept, dropped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
