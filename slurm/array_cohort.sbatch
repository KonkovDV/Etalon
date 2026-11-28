#!/usr/bin/env bash
# Many samples: one Slurm array task per line of a sample sheet.
# This is the population-scale pattern (thousands of genomes): one sample
# failing does not stop the others, and %N throttles load on shared storage.
#
#   N=$(($(wc -l < slurm/samples.tsv) - 1))
#   sbatch --array=1-${N}%20 slurm/array_cohort.sbatch slurm/samples.tsv
#
# samples.tsv: tab-separated, header line, columns sample  reads_1  reads_2.
# Samples without a truth set (everything except reference material) run with
# empty truth lists: the hap.py scatter is then empty and the report has no
# benchmark section; the QC gate still checks reads, mapping and Ti/Tv.
#SBATCH --job-name=mini-wgs-cohort
#SBATCH --cpus-per-task=4
#SBATCH --mem=4G
#SBATCH --time=00:30:00
#SBATCH --output=logs/%x-%A_%a.out
#SBATCH --error=logs/%x-%A_%a.out

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(pwd)}"
mkdir -p logs
# shellcheck disable=SC1091  # the venv exists on the cluster, not in the repository
[[ -f .venv/bin/activate ]] && source .venv/bin/activate

SHEET="${1:-slurm/samples.tsv}"
TASK="${SLURM_ARRAY_TASK_ID:?run as an array job: sbatch --array=1-N ...}"
# line TASK+1 (line 1 is the header)
IFS=$'\t' read -r SAMPLE R1 R2 < <(sed -n "$((TASK + 1))p" "${SHEET}")
[[ -n "${SAMPLE:-}" ]] || { echo "no line ${TASK} in ${SHEET}" >&2; exit 2; }
for f in "${R1}" "${R2}"; do [[ -s "${f}" ]] || { echo "missing ${f}" >&2; exit 2; }; done

OUT="results/cohort/${SAMPLE}"
if [[ -s "${OUT}/${SAMPLE}.vcf.gz" ]]; then
  echo "${SAMPLE}: already done, skipping (delete ${OUT} to rerun)"; exit 0
fi

file_json() { printf '{"class":"File","location":"%s","format":"http://edamontology.org/format_1930"}' "$(realpath "$1")"; }
export CWL_WORKDIR="${TMPDIR:-/tmp}/cwl-${SLURM_JOB_ID:-local}"
RUNNER="${RUNNER:-apptainer}" scripts/run_pipeline.sh -o "${OUT}" \
  sample="\"${SAMPLE}\"" \
  reads_1="$(file_json "${R1}")" reads_2="$(file_json "${R2}")" \
  threads="${SLURM_CPUS_PER_TASK:-4}" \
  'truth_names=[]' 'truth_vcfs=[]' 'truth_beds=[]'

python3 scripts/qc_gate.py "${OUT}/${SAMPLE}.report.json" --junit "${OUT}/qc-junit.xml"
python3 scripts/results_db.py --db results/cohort/results.sqlite ingest "${OUT}" --label "${SAMPLE}"
