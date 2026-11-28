#!/usr/bin/env bash
# Convert the workflow's container images to Apptainer .sif files once, on a
# node with internet access, into ${CWL_SINGULARITY_CACHE} on shared storage.
# Compute nodes then never pull anything.
#
# cwltool --singularity looks for "<dockerPull with / replaced by _>.sif" in
# CWL_SINGULARITY_CACHE, so the file names below are not arbitrary.
#
#   slurm/build_sif.sh                                   # tools image from the local Docker daemon
#   TOOLS_REF=docker://registry.gitlab.com/<group>/hg002-mini-wgs/tools:1.0.0 slurm/build_sif.sh
set -euo pipefail

CACHE="${CWL_SINGULARITY_CACHE:-$(pwd)/.sif}"
mkdir -p "${CACHE}"
APPTAINER="$(command -v apptainer || command -v singularity)" || { echo "apptainer not found" >&2; exit 2; }

TOOLS_TAG="hg002-mini/tools:1.0.0"
TOOLS_REF="${TOOLS_REF:-docker-daemon://${TOOLS_TAG}}"
HAPPY_REF="quay.io/biocontainers/hap.py@sha256:d63b963a6cb01b4830393b22369e7b91d298e4156dde353739e74e4cfa4f96d0"

build() {  # build SIF_NAME SOURCE
  local dest="${CACHE}/$1"
  if [[ -s "${dest}" ]]; then echo "exists: ${dest}"; return; fi
  "${APPTAINER}" build "${dest}.part" "$2"
  mv "${dest}.part" "${dest}"
  echo "built: ${dest}"
}

build "${TOOLS_TAG//\//_}.sif" "${TOOLS_REF}"
build "${HAPPY_REF//\//_}.sif" "docker://${HAPPY_REF}"
ls -la "${CACHE}"
