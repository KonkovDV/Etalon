#!/usr/bin/env bash
# Are the RNA-seq counts the same when the workflow is run again?
#
#   scripts/check_rnaseq_reproducibility.sh [RUN_A] [RUN_B] [REPORT]
#
# With no arguments it runs cwl/workflows/rnaseq.cwl twice, A with 4 threads and
# B with 2: STAR maps reads in parallel chunks and sorts the BAM in parallel bins,
# featureCounts splits the work between threads, so a different thread count is
# the harder test. Given two result directories it only compares them.
#
# Levels (all are reported; "required" ones decide the exit code):
#   counts matrix           rnaseq.counts.tsv, the result the analysis uses
#   featureCounts table     without its first line (the command with -T N)
#   STAR gene counts        ReadsPerGene.out.tab of every sample
#   splice junctions        SJ.out.tab of every sample
#   BAM records             alignments of every sample, without header
#   report numbers          rnaseq.report.json without timings and the thread count
#   BAM header / bytes      informational: @PG and @CO hold --runThreadN N; with equal
#                           thread counts both must match (BAM re-blocked by htslib, D-20)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${TOOLS_IMAGE:-hg002-mini/tools:1.0.0}"
A="${1:-${ROOT}/results/rnaseq_repro_t4}"
B="${2:-${ROOT}/results/rnaseq_repro_t2}"
report="${3:-${ROOT}/results/rnaseq_reproducibility.md}"
SAMPLES=(UHR_Rep1 UHR_Rep2 UHR_Rep3 HBR_Rep1 HBR_Rep2 HBR_Rep3)

if [[ $# -eq 0 ]]; then
  for run in "${A}:4" "${B}:2"; do
    "${ROOT}/scripts/run_pipeline.sh" -w "${ROOT}/cwl/workflows/rnaseq.cwl" \
      -j "${ROOT}/cwl/jobs/rnaseq-uhr-hbr.yml" -o "${run%:*}" "threads=${run##*:}"
  done
fi
# docker -v needs absolute paths; a relative one is taken as a volume name (D-09)
A="$(cd "${A}" && pwd)"
B="$(cd "${B}" && pwd)"

in_tools() {  # run a command in the tools image with both result dirs mounted
  docker run --rm -u "$(id -u):$(id -g)" -v "${A}:/a:ro" -v "${B}:/b:ro" "${IMAGE}" bash -c "$1"
}
sha_files() {  # sha256 of the concatenation of files, 16 hex digits
  cat "$@" | sha256sum | cut -c1-16
}
per_sample() {  # per_sample DIR SUFFIX -> list of files in sample order
  local d="$1" suffix="$2" s
  for s in "${SAMPLES[@]}"; do printf '%s\n' "${d}/${s}${suffix}"; done
}
report_numbers() {  # report JSON without timings, step list and thread count
  python3 - "$1" <<'PY'
import hashlib, json, sys
rep = json.load(open(sys.argv[1]))
for k in ("steps", "totals", "threads"):
    rep.pop(k, None)
print(hashlib.sha256(json.dumps(rep, sort_keys=True).encode()).hexdigest()[:16])
PY
}

verdict=0
mkdir -p "$(dirname "${report}")"
{
  echo "# Воспроизводимость RNA-seq: $(basename "${A}") против $(basename "${B}")"
  echo
  echo "| уровень | A | B | совпадает |"
  echo "|---|---|---|---|"
} > "${report}"

row() {  # row LEVEL HASH_A HASH_B required|informational
  local same="да"
  if [[ -z "$2" || -z "$3" ]]; then  # an empty hash is a failed command, never "identical"
    echo "ERROR: empty checksum for '$1' (command failed)" >&2
    exit 3
  fi
  if [[ "$2" != "$3" ]]; then
    same="нет"
    [[ "$4" == "required" ]] && verdict=1
  fi
  echo "| $1 | \`$2\` | \`$3\` | ${same} |" >> "${report}"
  printf '%-32s %s  %s  %s\n' "$1" "$2" "$3" "${same}"
}

# Hashes go into variables first: under `set -e` a failing substitution in an
# assignment stops the script, inside an argument list it does not.
va=$(sha_files "${A}/rnaseq.counts.tsv"); vb=$(sha_files "${B}/rnaseq.counts.tsv")
row "матрица счётов (counts.tsv)" "${va}" "${vb}" required
va=$(sed 1d "${A}/featureCounts.txt" | sha256sum | cut -c1-16)
vb=$(sed 1d "${B}/featureCounts.txt" | sha256sum | cut -c1-16)
row "featureCounts, таблица" "${va}" "${vb}" required
va=$(sha_files "${A}/featureCounts.txt.summary"); vb=$(sha_files "${B}/featureCounts.txt.summary")
row "featureCounts, сводка" "${va}" "${vb}" required
mapfile -t fa < <(per_sample "${A}" .ReadsPerGene.out.tab)
mapfile -t fb < <(per_sample "${B}" .ReadsPerGene.out.tab)
va=$(sha_files "${fa[@]}"); vb=$(sha_files "${fb[@]}")
row "STAR, счёт по генам" "${va}" "${vb}" required
mapfile -t fa < <(per_sample "${A}" .SJ.out.tab)
mapfile -t fb < <(per_sample "${B}" .SJ.out.tab)
va=$(sha_files "${fa[@]}"); vb=$(sha_files "${fb[@]}")
row "STAR, сплайс-сочленения" "${va}" "${vb}" required
bams="${SAMPLES[*]/%/.bam}"
va=$(in_tools "set -o pipefail; cd /a && for f in ${bams}; do samtools view \$f; done | sha256sum | cut -c1-16")
vb=$(in_tools "set -o pipefail; cd /b && for f in ${bams}; do samtools view \$f; done | sha256sum | cut -c1-16")
row "BAM, выравнивания" "${va}" "${vb}" required
va=$(report_numbers "${A}/rnaseq.report.json"); vb=$(report_numbers "${B}/rnaseq.report.json")
row "числа отчёта" "${va}" "${vb}" required
# --no-PG: otherwise `samtools view -H` appends its own @PG line with /a or /b in it
va=$(in_tools "set -o pipefail; cd /a && for f in ${bams}; do samtools view --no-PG -H \$f; done | sha256sum | cut -c1-16")
vb=$(in_tools "set -o pipefail; cd /b && for f in ${bams}; do samtools view --no-PG -H \$f; done | sha256sum | cut -c1-16")
row "BAM, заголовки" "${va}" "${vb}" informational
mapfile -t fa < <(per_sample "${A}" .bam)
mapfile -t fb < <(per_sample "${B}" .bam)
va=$(sha_files "${fa[@]}"); vb=$(sha_files "${fb[@]}")
row "BAM, байты (sha256)" "${va}" "${vb}" informational

{
  echo
  if (( verdict == 0 )); then
    echo "**Итог: счёты, выравнивания и числа отчёта совпадают.** Заголовок BAM может отличаться только строками @PG и @CO с \`--runThreadN N\`."
  else
    echo "**Итог: результаты различаются.** См. docs/RNASEQ.md."
  fi
} >> "${report}"
echo "report: ${report}" >&2
exit "${verdict}"
