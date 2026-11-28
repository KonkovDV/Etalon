#!/usr/bin/env bash
# Do different callers write the same variants differently?
#
#   scripts/compare_representation.sh OUT name=VCF name=VCF [name=VCF ...]
#
# For a frequency database, every distinct (CHROM, POS, REF, ALT) is a separate
# variant. Callers that see the same haplotype can still write it differently: a
# multi-allelic record or two bi-allelic ones, an indel shifted within a repeat,
# one delins or an SNV next to an indel. This script keeps the PASS calls of each
# caller, runs hap.py for every pair (first caller as truth, second as query) in
# the GIAB v5.0q benchmark regions, and lets scripts/representation.py count how
# many "different" variants are the same haplotype written another way.
#
# Output: OUT/<name>.pass.vcf.gz, OUT/pairs/<a>_vs_<b>/*, OUT/representation.{json,md}
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="${TOOLS_IMAGE:-hg002-mini/tools:1.0.0}"
HAPPY="${HAPPY_IMAGE:-quay.io/biocontainers/hap.py@sha256:d63b963a6cb01b4830393b22369e7b91d298e4156dde353739e74e4cfa4f96d0}"
BED="${BED:-${ROOT}/data/truth/giab_v5.0q.bed}"
DIFFICULT="${DIFFICULT:-${ROOT}/data/strat/all_difficult.bed}"
REF="${REF:-${ROOT}/data/ref/ref.fa}"
THREADS="${THREADS:-4}"

if [[ $# -lt 3 ]]; then
  sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
fi
OUT="$1"
shift
mkdir -p "${OUT}/pairs"
OUT="$(cd "${OUT}" && pwd)"

names=()
for item in "$@"; do
  name="${item%%=*}" vcf="${item#*=}"
  [[ -s "${vcf}" ]] || { echo "missing VCF: ${vcf}" >&2; exit 2; }
  vcf="$(cd "$(dirname "${vcf}")" && pwd)/$(basename "${vcf}")"
  docker run --rm -u "$(id -u):$(id -g)" -v "$(dirname "${vcf}"):/in:ro" -v "${OUT}:/out" "${TOOLS}" \
    bash -c "bcftools view --no-version -f PASS -Oz -o /out/${name}.pass.vcf.gz /in/$(basename "${vcf}") \
      && tabix -f -p vcf /out/${name}.pass.vcf.gz"
  names+=("${name}")
done

for ((i = 0; i < ${#names[@]}; i++)); do
  for ((j = i + 1; j < ${#names[@]}; j++)); do
    a="${names[i]}" b="${names[j]}"
    pair="${OUT}/pairs/${a}_vs_${b}"
    mkdir -p "${pair}"
    [[ -s "${pair}/happy.vcf.gz" ]] && continue
    docker run --rm -u "$(id -u):$(id -g)" -v "${OUT}:/w" -v "$(dirname "${REF}"):/ref:ro" \
      -v "$(dirname "${BED}"):/bed:ro" "${HAPPY}" \
      hap.py "/w/${a}.pass.vcf.gz" "/w/${b}.pass.vcf.gz" -f "/bed/$(basename "${BED}")" \
        -r "/ref/$(basename "${REF}")" -o "/w/pairs/${a}_vs_${b}/happy" --engine xcmp \
        --threads "${THREADS}" --scratch-prefix /w/pairs > "${pair}/happy.log" 2>&1
  done
done

args=()
for n in "${names[@]}"; do args+=("${n}=${OUT}/${n}.pass.vcf.gz"); done
extra=()
[[ -s "${DIFFICULT}" ]] && extra=(--difficult "${DIFFICULT}")
python3 "${ROOT}/scripts/representation.py" --ref "${REF}" --bed "${BED}" --pairs "${OUT}/pairs" \
  --json "${OUT}/representation.json" --md "${OUT}/representation.md" ${extra[@]+"${extra[@]}"} "${args[@]}"
echo "report: ${OUT}/representation.md" >&2
