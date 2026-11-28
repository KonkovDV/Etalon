#!/usr/bin/env bash
# Accuracy against depth: thin the read pairs, then run the WGS pipeline and the
# callers at every depth.
#
#   scripts/depth_series.sh [OUT]          # default results/depth; finished points are skipped
#   CALLERS="strelka2" scripts/depth_series.sh
#
# Thinning keeps or drops whole pairs: `samtools view -s SEED.FRACTION` hashes the
# read name with the seed, so the same seed gives the same subset on any machine
# and with any thread count. Fractions are of the full ~34.5x set, seed 1 at every
# depth; seeds 2 and 3 at REPLICATED depths show how much a point moves when
# only the random subset changes. DeepVariant runs on seed 1 only (CPU-heavy).
#
# Layout: OUT/f<fraction>_s<seed>/{reads,run,strelka2,deepvariant}. The summary is
# built by scripts/depth_curve.py.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-${ROOT}/results/depth}"
IMAGE="${TOOLS_IMAGE:-hg002-mini/tools:1.0.0}"
THREADS="${THREADS:-4}"
read -r -a CALLERS <<< "${CALLERS:-strelka2 deepvariant}"
FRACTIONS=(1.0 0.87 0.725 0.58 0.435 0.29 0.145)  # ~35, 30, 25, 20, 15, 10, 5x
REPLICATED=(0.58 0.29)                           # extra seeds 2 and 3 here
mkdir -p "${OUT}"
OUT="$(cd "${OUT}" && pwd)"

log() { printf '[depth %(%H:%M:%S)T] %s\n' -1 "$*" >&2; }

thin() {  # thin FRACTION SEED DIR -> DIR/reads/HG002_R{1,2}.fastq.gz
  local frac="$1" seed="$2" dir="$3"
  mkdir -p "${dir}/reads"
  if [[ "${frac}" == "1.0" ]]; then
    ln -sf "${ROOT}/data/reads/HG002_R1.fastq.gz" "${dir}/reads/HG002_R1.fastq.gz"
    ln -sf "${ROOT}/data/reads/HG002_R2.fastq.gz" "${dir}/reads/HG002_R2.fastq.gz"
    return
  fi
  [[ -s "${dir}/reads/HG002_R2.fastq.gz" ]] && return
  docker run --rm -u "$(id -u):$(id -g)" -v "${ROOT}/data/reads:/r:ro" -v "${dir}/reads:/o" "${IMAGE}" \
    bash -c "set -euo pipefail
      samtools import -1 /r/HG002_R1.fastq.gz -2 /r/HG002_R2.fastq.gz -u -o - \
        | samtools view -u -s ${seed}.${frac#0.} - \
        | samtools fastq -n -c 6 -1 /o/HG002_R1.fastq.gz -2 /o/HG002_R2.fastq.gz -0 /dev/null -s /dev/null - 2>/dev/null"
}

point() {  # point FRACTION SEED CALLER...
  local frac="$1" seed="$2"
  shift 2
  local dir="${OUT}/f${frac}_s${seed}"
  thin "${frac}" "${seed}" "${dir}"
  if [[ ! -s "${dir}/run/HG002.report.json" ]]; then
    log "f${frac}_s${seed}: WGS pipeline"
    "${ROOT}/scripts/run_pipeline.sh" -o "${dir}/run" "threads=${THREADS}" \
      "reads_1=${dir}/reads/HG002_R1.fastq.gz" "reads_2=${dir}/reads/HG002_R2.fastq.gz" > "${dir}/run.log" 2>&1
  fi
  local c
  for c in "$@"; do
    [[ -s "${dir}/${c}/giab_v5.0q.summary.csv" ]] && continue
    log "f${frac}_s${seed}: ${c}"
    "${ROOT}/scripts/run_pipeline.sh" -w "${ROOT}/cwl/workflows/call-${c}.cwl" -o "${dir}/${c}" \
      "bam=${dir}/run/HG002.bam" "reference=${ROOT}/data/ref/ref.fa" "threads=${THREADS}" > "${dir}/${c}.log" 2>&1
  done
}

for f in "${FRACTIONS[@]}"; do
  point "${f}" 1 "${CALLERS[@]}"
done
light=()
for c in "${CALLERS[@]}"; do [[ "${c}" == deepvariant ]] || light+=("${c}"); done
for f in "${REPLICATED[@]}"; do
  for s in 2 3; do
    point "${f}" "${s}" ${light[@]+"${light[@]}"}
  done
done
log "done: ${OUT}"
