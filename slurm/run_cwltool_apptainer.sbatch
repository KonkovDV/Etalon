#!/usr/bin/env bash
# Whole workflow on ONE node: cwltool + Apptainer (no Docker daemon on HPC nodes).
#
#   sbatch slurm/run_cwltool_apptainer.sbatch
#   sbatch --cpus-per-task=8 slurm/run_cwltool_apptainer.sbatch      # threads follow the allocation
#
# Before the first run, on a node with internet (usually the login node):
#   slurm/build_sif.sh            # converts both images to .sif in ${CWL_SINGULARITY_CACHE}
#
# Resources come from measured numbers, not guesses: the largest step (fastp)
# peaks at ~1.1 GB RSS and the whole run takes ~1 min at 4 threads
# (results/*/HG002.step_metrics.tsv). 4 GB / 30 min leave room for slower nodes.
#SBATCH --job-name=hg002-mini-wgs
#SBATCH --cpus-per-task=4
#SBATCH --mem=4G
#SBATCH --time=00:30:00
#SBATCH --output=logs/%x-%j.out
#SBATCH --error=logs/%x-%j.out
##SBATCH --partition=short          # site-specific: uncomment and set
##SBATCH --account=bioinf           # site-specific: uncomment and set

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:-$(pwd)}"
mkdir -p logs

# Site-specific environment (module names differ between clusters)
if command -v module >/dev/null 2>&1; then
  module load apptainer 2>/dev/null || module load singularity 2>/dev/null || true
fi
# cwltool in a project venv: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
# shellcheck disable=SC1091  # the venv exists on the cluster, not in the repository
[[ -f .venv/bin/activate ]] && source .venv/bin/activate

export CWL_SINGULARITY_CACHE="${CWL_SINGULARITY_CACHE:-${PWD}/.sif}"   # prebuilt images, shared FS
export APPTAINER_CACHEDIR="${APPTAINER_CACHEDIR:-${PWD}/.apptainer-cache}"
# Scratch on node-local disk: many small temporary files must not hit the shared FS
export CWL_WORKDIR="${TMPDIR:-/tmp}/cwl-${SLURM_JOB_ID:-local}"

OUT="results/slurm-${SLURM_JOB_ID:-local}"
echo "[$(date -Is)] node=$(hostname) cpus=${SLURM_CPUS_PER_TASK:-4} out=${OUT}"

RUNNER="${RUNNER:-apptainer}" scripts/run_pipeline.sh -o "${OUT}" threads="${SLURM_CPUS_PER_TASK:-4}"
python3 scripts/qc_gate.py "${OUT}/HG002.report.json" --junit "${OUT}/qc-junit.xml"

echo "[$(date -Is)] done. After the job finishes compare with Slurm's own accounting:"
echo "  sacct -j ${SLURM_JOB_ID:-<id>} --format=JobID,Elapsed,TotalCPU,MaxRSS,State"
echo "  seff ${SLURM_JOB_ID:-<id>}"
