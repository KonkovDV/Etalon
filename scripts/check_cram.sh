#!/usr/bin/env bash
# BAM against CRAM: how much space CRAM saves, what it costs in time, and whether
# anything is lost on the way.
#
#   scripts/check_cram.sh [OUT] [BAM] [REF]     # defaults: results/cram, results/run/HG002.bam, data/ref/ref.fa
#
# Three CRAM variants of the same BAM are written with samtools from the tools image:
# CRAM 3.0 (what samtools 1.13 writes by default), CRAM 3.1 (the default since
# samtools 1.22) and CRAM 3.1 with the archive profile (stronger codecs, slower).
# For each the script records the size of the file and its index, the time to write
# it and to read it back in full on one thread, and three checks:
#   sam_bytes — `samtools view` of the CRAM gives byte for byte the SAM text of the BAM;
#   records   — the same, with the optional fields of each record compared as a set.
#               The SAM specification does not fix their order, and CRAM does change it:
#               MD and NM are not stored but rebuilt on reading and put last;
#   calls     — the same `bcftools mpileup | call` on the CRAM gives the same VCF bytes.
# CRAM keeps the reads relative to the reference, so the reference (and its MD5 in the
# @SQ lines) must stay available for as long as the CRAM is kept.
#
# Output: OUT/cram.tsv and OUT/versions.txt; scripts/cram_report.py builds the JSON and Markdown.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-${ROOT}/results/cram}"
BAM="${2:-${ROOT}/results/run/HG002.bam}"
REF="${3:-${ROOT}/data/ref/ref.fa}"
IMAGE="${TOOLS_IMAGE:-hg002-mini/tools:1.0.0}"
for f in "${BAM}" "${BAM}.bai" "${REF}" "${REF}.fai"; do
  [[ -s "${f}" ]] || { echo "missing: ${f}" >&2; exit 2; }
done
mkdir -p "${OUT}"
OUT="$(cd "${OUT}" && pwd)"
BAM="$(cd "$(dirname "${BAM}")" && pwd)/$(basename "${BAM}")"
REF="$(cd "$(dirname "${REF}")" && pwd)/$(basename "${REF}")"

docker run --rm -i -u "$(id -u):$(id -g)" \
  -v "$(dirname "${BAM}"):/bam:ro" -v "$(dirname "${REF}"):/ref:ro" -v "${OUT}:/out" \
  -e BAM="/bam/$(basename "${BAM}")" -e REF="/ref/$(basename "${REF}")" \
  "${IMAGE}" bash -s <<'INSIDE'
set -euo pipefail
cd /out

seconds() {  # wall time of a command, its stdout discarded
  local t0 t1
  t0=$(date +%s.%N); "$@" > /dev/null; t1=$(date +%s.%N)
  awk -v a="${t0}" -v b="${t1}" 'BEGIN { printf "%.3f", b - a }'
}
decode() { samtools view --no-PG -T "${REF}" -O sam -o /dev/null "$1"; }  # full decode, as a reader would
sam_text() { samtools view --no-PG -T "${REF}" "$1"; }
sam_hash() { sam_text "$1" | sha256sum | cut -d' ' -f1; }
record_hash() {  # optional fields of every record sorted: their order is not significant in SAM
  sam_text "$1" | perl -F'\t' -lane 'print join "\t", @F[0..10], sort @F[11..$#F]' | sha256sum | cut -d' ' -f1
}
call_hash() {
  bcftools mpileup --no-version -X illumina -f "${REF}" -q 20 -Q 20 --max-depth 500 \
      -a FORMAT/AD,FORMAT/DP,FORMAT/SP,INFO/AD -Ou "$1" 2> /dev/null \
    | bcftools call --no-version -m -v -Ov 2> /dev/null | sha256sum | cut -d' ' -f1
}
encode() {  # encode FILE FORMAT-OPTIONS
  samtools view --no-PG -T "${REF}" -O "$2" -o "$1" "${BAM}" && samtools index "$1"
}
yes_no() { [[ "$1" == "$2" ]] && echo yes || echo no; }

bam_sam=$(sam_hash "${BAM}")
bam_records=$(record_hash "${BAM}")
bam_calls=$(call_hash "${BAM}")
bam_read=$(seconds decode "${BAM}")
printf 'format\tbytes\tindex_bytes\twrite_s\tread_s\tsam_bytes_identical\trecords_identical\tcalls_identical\n' > cram.tsv
printf 'BAM\t%s\t%s\t\t%s\tyes\tyes\tyes\n' "$(stat -c %s "${BAM}")" "$(stat -c %s "${BAM}.bai")" "${bam_read}" >> cram.tsv
for spec in "CRAM 3.0|HG002.v30.cram|cram,version=3.0" "CRAM 3.1|HG002.v31.cram|cram,version=3.1" \
            "CRAM 3.1 archive|HG002.v31a.cram|cram,version=3.1,archive"; do
  IFS='|' read -r label file opts <<< "${spec}"
  write_s=$(seconds encode "${file}" "${opts}")
  read_s=$(seconds decode "${file}")
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "${label}" "$(stat -c %s "${file}")" "$(stat -c %s "${file}.crai")" \
    "${write_s}" "${read_s}" "$(yes_no "$(sam_hash "${file}")" "${bam_sam}")" \
    "$(yes_no "$(record_hash "${file}")" "${bam_records}")" "$(yes_no "$(call_hash "${file}")" "${bam_calls}")" >> cram.tsv
done
samtools --version | head -2 > versions.txt
INSIDE
cat "${OUT}/cram.tsv"
