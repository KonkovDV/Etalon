#!/usr/bin/env bash
# Check that scripts/concordance.py normalizes variants exactly like
# `bcftools norm -m -any -f ref` (split multiallelic records, trim, left-align).
#
#   scripts/check_normalization.sh VCF [VCF ...] > docs/results/metrics/normalization_check.md
#
# bcftools runs in the tools image; the comparison is done by concordance.py norm-check.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS_IMAGE="${TOOLS_IMAGE:-hg002-mini/tools:1.0.0}"
REF="${REF:-data/ref/ref.fa}"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

[[ $# -gt 0 ]] || { sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
for vcf in "$@"; do
  name="$(basename "${vcf}" .vcf.gz)"
  docker run --rm -u "$(id -u):$(id -g)" -v "${ROOT}":/work -v "${TMP}":/out -w /work "${TOOLS_IMAGE}" \
    bash -c "set -o pipefail; bcftools norm --no-version -m -any -f '${REF}' '${vcf}' 2>/dev/null \
      | bcftools query -f '%CHROM\t%POS\t%REF\t%ALT\t[%GT]\n' > '/out/${name}.bcftools.tsv'"
done
cd "${ROOT}"
python3 scripts/concordance.py norm-check "${REF}" "${TMP}" "$@"
