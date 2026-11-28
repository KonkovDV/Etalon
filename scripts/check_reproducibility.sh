#!/usr/bin/env bash
# Is the VCF the same when the pipeline is run again?
#
#   scripts/check_reproducibility.sh [RUN_A] [RUN_B]
#
# With no arguments it runs the workflow twice: A with 4 threads, B with 2.
# A different thread count is the harder test: it changes how bwa-mem2,
# samtools and fastp split work, and with it any order-dependent result.
# Given two existing result directories it only compares them.
#
# Levels, from strict to loose (all are reported, the first is required):
#   1. VCF bytes         sha256 of the bgzipped file (header + records + BGZF blocks)
#   2. VCF records       records without header
#   3. BAM records       alignments without header (header holds @PG with -t N;
#                        with equal thread counts the BAM is byte-identical too)
#   4. hap.py summary    benchmark numbers
#   5. FASTQ after fastp (not a workflow output; covered by tests/test_fastp_determinism.sh)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${TOOLS_IMAGE:-hg002-mini/tools:1.0.0}"
A="${1:-${ROOT}/results/repro_t4}"
B="${2:-${ROOT}/results/repro_t2}"

if [[ $# -eq 0 ]]; then
  "${ROOT}/scripts/run_pipeline.sh" -o "${A}" threads=4
  "${ROOT}/scripts/run_pipeline.sh" -o "${B}" threads=2
fi
# docker -v needs absolute paths; a relative one is taken as a volume name
A="$(cd "${A}" && pwd)"
B="$(cd "${B}" && pwd)"

in_tools() {  # run a command in the tools image with both result dirs mounted
  docker run --rm -u "$(id -u):$(id -g)" -v "${A}:/a:ro" -v "${B}:/b:ro" "${IMAGE}" bash -c "$1"
}

sha() { sha256sum "$1" | cut -c1-16; }
verdict=0
report="${ROOT}/results/reproducibility.md"
{
  echo "# Воспроизводимость: $(basename "${A}") против $(basename "${B}")"
  echo
  echo "| уровень | A | B | совпадает |"
  echo "|---|---|---|---|"
} > "${report}"

row() {  # row LEVEL HASH_A HASH_B REQUIRED
  local same="да"
  # An empty hash means the command failed. Never let "" == "" pass as identical
  # (this happened once: see docs/DEBUGGING.md, D-09).
  if [[ -z "$2" || -z "$3" ]]; then
    echo "ERROR: empty checksum for '$1' (command failed)" >&2
    exit 3
  fi
  if [[ "$2" != "$3" ]]; then
    same="нет"
    [[ "$4" == "required" ]] && verdict=1
  fi
  echo "| $1 | \`$2\` | \`$3\` | ${same} |" >> "${report}"
  printf '%-28s %s  %s  %s\n' "$1" "$2" "$3" "${same}"
}

# Hashes are computed into variables first: under `set -e` a failing command
# substitution in an assignment stops the script, inside an argument list it does not.
va=$(sha "${A}/HG002.vcf.gz");  vb=$(sha "${B}/HG002.vcf.gz")
row "VCF, байты (sha256)" "${va}" "${vb}" required
va=$(in_tools 'set -o pipefail; bcftools view -H /a/HG002.vcf.gz | sha256sum | cut -c1-16')
vb=$(in_tools 'set -o pipefail; bcftools view -H /b/HG002.vcf.gz | sha256sum | cut -c1-16')
row "VCF, записи" "${va}" "${vb}" required
va=$(in_tools 'set -o pipefail; samtools view /a/HG002.bam | sha256sum | cut -c1-16')
vb=$(in_tools 'set -o pipefail; samtools view /b/HG002.bam | sha256sum | cut -c1-16')
row "BAM, выравнивания" "${va}" "${vb}" required
for t in giab_v5.0q giab_v4.2.1; do
  [[ -f "${A}/${t}.summary.csv" ]] || continue
  va=$(sha "${A}/${t}.summary.csv"); vb=$(sha "${B}/${t}.summary.csv")
  row "hap.py ${t}" "${va}" "${vb}" required
done
# --no-PG: otherwise `samtools view -H` appends its own @PG line with /a or /b in it
va=$(in_tools 'set -o pipefail; samtools view --no-PG -H /a/HG002.bam | sha256sum | cut -c1-16')
vb=$(in_tools 'set -o pipefail; samtools view --no-PG -H /b/HG002.bam | sha256sum | cut -c1-16')
row "BAM, заголовок" "${va}" "${vb}" informational
va=$(sha "${A}/HG002.bam"); vb=$(sha "${B}/HG002.bam")
row "BAM, байты (sha256)" "${va}" "${vb}" informational

{
  echo
  if (( verdict == 0 )); then
    echo "**Итог: VCF побайтно одинаковый.** Заголовок BAM может отличаться только строкой @PG с \`-t N\`."
  else
    echo "**Итог: результаты различаются.** См. docs/REPRODUCIBILITY.md."
  fi
} >> "${report}"
echo "report: ${report}" >&2
exit "${verdict}"
