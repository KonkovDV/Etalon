#!/usr/bin/env bash
# Run the CWL workflow with cwltool in Docker (or Apptainer/Singularity).
#
#   scripts/run_pipeline.sh                          # -> results/run
#   scripts/run_pipeline.sh -o results/t2 threads=2
#   scripts/run_pipeline.sh -o results/legacy 'mpileup_profile=""'
#   RUNNER=apptainer scripts/run_pipeline.sh         # cwltool --singularity (HPC without Docker)
#   scripts/run_pipeline.sh -w cwl/workflows/call-strelka2.cwl -o results/callers/strelka2 bam=results/run/HG002.bam
#
# key=value arguments override workflow inputs of the job file; inputs the
# workflow does not have are dropped (scripts/make_job.py --for -> <outdir>/job.json).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${ROOT}/results/run"
JOB="${ROOT}/cwl/jobs/hg002-chr20.yml"
WF="${ROOT}/cwl/workflows/mini-wgs.cwl"
RUNNER="${RUNNER:-docker}"
overrides=()

usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }
while [[ $# -gt 0 ]]; do
  case "$1" in
    -o|--outdir) OUT="$2"; shift 2 ;;
    -j|--job)    JOB="$2"; shift 2 ;;
    -w|--workflow) WF="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"; shift 2 ;;
    -h|--help)   usage 0 ;;
    *=*)         overrides+=("$1"); shift ;;
    *)           echo "unknown argument: $1" >&2; usage 2 ;;
  esac
done

command -v cwltool >/dev/null || { echo "cwltool not found: pip install -r requirements.txt" >&2; exit 2; }

# Keep cwltool's scratch space next to the results: on clusters /tmp is often
# small, and in GitLab CI with docker:dind only the project dir is shared with
# the Docker daemon.
WORK="${CWL_WORKDIR:-${OUT}.work}"
mkdir -p "${OUT}" "${WORK}/tmp" "${WORK}/out"
python3 "${ROOT}/scripts/make_job.py" --for "${WF}" "${JOB}" ${overrides[@]+"${overrides[@]}"} > "${OUT}/job.json"

runner_flags=()
# CWL_EXTRA_FLAGS: extra cwltool flags as one string, split on spaces on purpose
read -r -a extra_flags <<< "${CWL_EXTRA_FLAGS:-}"
case "${RUNNER}" in
  docker) ;;
  apptainer|singularity) runner_flags+=(--singularity) ;;
  none) runner_flags+=(--no-container) ;;  # debugging only: tools from PATH
  *) echo "RUNNER must be docker|apptainer|singularity|none" >&2; exit 2 ;;
esac

set -x
cwltool \
  --timestamps \
  --disable-color \
  "${runner_flags[@]}" \
  --tmpdir-prefix "${WORK}/tmp/" \
  --tmp-outdir-prefix "${WORK}/out/" \
  --outdir "${OUT}" \
  ${extra_flags[@]+"${extra_flags[@]}"} \
  "${WF}" "${OUT}/job.json" \
  > "${OUT}/cwl_outputs.json" 2> >(tee "${OUT}/cwltool.log" >&2)
set +x
rm -rf "${WORK}"
echo "outputs: ${OUT}" >&2
