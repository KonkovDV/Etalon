#!/usr/bin/env bash
# Workflow DISTRIBUTED over the cluster: a small Toil leader job submits every
# CWL step as its own Slurm job, sized by the step's ResourceRequirement
# (coresMin / ramMin in cwl/tools/*.cwl). Scatter (one hap.py per truth set)
# runs in parallel on different nodes.
#
#   sbatch slurm/run_toil_slurm.sbatch
#
# The leader itself needs little: 1 CPU, 2 GB, but must live as long as the workflow.
#SBATCH --job-name=hg002-toil-leader
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=04:00:00
#SBATCH --output=logs/%x-%j.out
#SBATCH --error=logs/%x-%j.out
##SBATCH --partition=long

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(pwd)}"
mkdir -p logs
# shellcheck disable=SC1091  # the venv exists on the cluster, not in the repository
[[ -f .venv/bin/activate ]] && source .venv/bin/activate   # pip install 'toil[cwl]'

RUN="slurm-toil-${SLURM_JOB_ID:-local}"
OUT="results/${RUN}"
mkdir -p "${OUT}" .toil   # Toil needs the jobStore parent to exist
python3 scripts/make_job.py cwl/jobs/hg002-chr20.yml > "${OUT}/job.json"

# Extra sbatch flags for every step job (partition, account, QoS):
export TOIL_SLURM_ARGS="${TOIL_SLURM_ARGS:-}"            # e.g. "--partition=short --account=bioinf"
export CWL_SINGULARITY_CACHE="${CWL_SINGULARITY_CACHE:-${PWD}/.sif}"

toil-cwl-runner \
  --batchSystem slurm \
  --jobStore "file:${PWD}/.toil/${RUN}" \
  --workDir "${TOIL_WORKDIR:-/tmp}" \
  --singularity \
  --outdir "${OUT}" \
  --logFile "${OUT}/toil.log" \
  --stats \
  --retryCount 2 \
  --maxCores 32 --maxMemory 64G \
  cwl/workflows/mini-wgs.cwl "${OUT}/job.json"

# Per-job CPU / memory as Toil saw them (complements bin/measure.py numbers)
toil stats "file:${PWD}/.toil/${RUN}" > "${OUT}/toil-stats.txt" || true
toil clean "file:${PWD}/.toil/${RUN}"
python3 scripts/qc_gate.py "${OUT}/HG002.report.json"
