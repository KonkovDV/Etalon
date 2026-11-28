#!/usr/bin/env bash
# Build the HG002 mini-dataset: paired FASTQ, a one-contig reference, two GIAB
# truth sets and GIAB stratifications, all on the same mini-contig coordinates.
#
#   scripts/prepare_data.sh            # uses config/dataset.env
#   REGION_END=10500000 scripts/prepare_data.sh   # smaller region
#
# Needs: samtools, bcftools, bgzip, tabix, python3, curl (all in the tools image;
# `make data` runs this script inside it). Only the requested region is
# transferred: htslib reads BAM/FASTA/VCF over HTTPS using their indexes.
#
# Result (data/):
#   ref/ref.fa(.fai)                        mini-reference, one contig
#   reads/HG002_R{1,2}.fastq.gz             raw paired reads
#   truth/<set>.vcf.gz(.tbi), <set>.bed     GIAB v5.0q and v4.2.1
#   strat/*.bed, strat/strata.tsv           GIAB stratifications v3.6
#   MANIFEST.sha256, SOURCES.tsv            checksums and provenance
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"
# shellcheck source=../config/dataset.env
source "${ROOT}/config/dataset.env"

log() { printf '[prepare_data %(%H:%M:%S)T] %s\n' -1 "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

for tool in samtools bcftools bgzip tabix python3 curl; do
  command -v "${tool}" >/dev/null || die "${tool} not found in PATH (run via 'make data')"
done

REGION="${REGION_CHROM}:${REGION_START}-${REGION_END}"
CONTIG="${REGION_CHROM}_${REGION_START}_${REGION_END}"
SHIFT=$((REGION_START - 1))
LENGTH=$((REGION_END - REGION_START + 1))
BENCH_START=$((REGION_START + EDGE_MARGIN))
BENCH_END=$((REGION_END - EDGE_MARGIN))
(( BENCH_END > BENCH_START )) || die "region shorter than 2 x EDGE_MARGIN"

mkdir -p "${DATA_DIR}"/{ref,reads,truth,strat} "${CACHE_DIR}"
TMP="$(mktemp -d "${DATA_DIR}/.tmp.XXXXXX")"
trap 'rm -rf "${TMP}"' EXIT
# htslib caches remote index files in the current directory; keep them out of the repo root
cd "${TMP}" && TMP="$(pwd)" && cd "${ROOT}"
DATA="$(cd "${DATA_DIR}" && pwd)"
CACHE="$(cd "${CACHE_DIR}" && pwd)"
SHIFT_PY="${ROOT}/scripts/shift_coords.py"

: > "${DATA}/SOURCES.tsv"
source_row() { printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "${DATA}/SOURCES.tsv"; }
printf 'file\tsource\tnote\n' > "${DATA}/SOURCES.tsv"

fetch() {  # fetch URL DEST [md5]; cached, retried, optionally md5-checked
  local url="$1" dest="$2" md5="${3:-}"
  if [[ ! -s "${dest}" ]]; then
    log "download ${url##*/}"
    curl -fsSL --retry 5 --retry-delay 5 -o "${dest}.part" "${url}"
    mv "${dest}.part" "${dest}"
  fi
  if [[ -n "${md5}" ]]; then
    echo "${md5}  ${dest}" | md5sum -c --quiet - || die "md5 mismatch: ${dest}"
  fi
}

########## 1. reference ###########################################################
log "reference: ${REGION} -> contig ${CONTIG} (${LENGTH} bp)"
( cd "${TMP}" && samtools faidx "${REFERENCE_URL}" "${REGION}" ) \
  | sed "1s/^>.*/>${CONTIG}/" > "${TMP}/ref.raw.fa"
# Normalise line length to 60 (faidx keeps the source width)
python3 - "${TMP}/ref.raw.fa" "${DATA}/ref/ref.fa" <<'PY'
import sys
name, seq = None, []
for line in open(sys.argv[1]):
    if line.startswith(">"):
        name = line.strip()
    else:
        seq.append(line.strip())
s = "".join(seq)
with open(sys.argv[2], "w") as out:
    out.write(name + "\n")
    for i in range(0, len(s), 60):
        out.write(s[i:i + 60] + "\n")
PY
samtools faidx "${DATA}/ref/ref.fa"
got_len="$(cut -f2 "${DATA}/ref/ref.fa.fai")"
[[ "${got_len}" == "${LENGTH}" ]] || die "reference length ${got_len} != ${LENGTH}"
N_COUNT="$(grep -v '^>' "${DATA}/ref/ref.fa" | tr -cd 'Nn' | wc -c)"
REF_MD5="$(grep -v '^>' "${DATA}/ref/ref.fa" | tr -d '\n' | tr 'acgtn' 'ACGTN' | md5sum | cut -d' ' -f1)"
log "reference md5 (uppercase, as in SAM @SQ M5) ${REF_MD5}; N bases: ${N_COUNT}"
source_row ref/ref.fa "${REFERENCE_URL}" "region ${REGION}; M5 ${REF_MD5}"

# Independent check: the same bases from UCSC hg38 (no-alt set == hg38 on chr20)
if [[ "${SKIP_UCSC_CHECK:-0}" != "1" ]]; then
  ucsc_md5="$(curl -fsSL --retry 3 "${UCSC_API}?genome=hg38;chrom=${REGION_CHROM};start=${SHIFT};end=${REGION_END}" \
    | python3 -c 'import sys,json,hashlib; print(hashlib.md5(json.load(sys.stdin)["dna"].upper().encode()).hexdigest())')" \
    || ucsc_md5="unavailable"
  if [[ "${ucsc_md5}" == "unavailable" ]]; then
    log "WARN: UCSC cross-check skipped (API unreachable)"
  elif [[ "${ucsc_md5}" != "${REF_MD5}" ]]; then
    die "reference differs from UCSC hg38 (${ucsc_md5} != ${REF_MD5})"
  else
    log "reference matches UCSC hg38 ${REGION} byte for byte"
  fi
fi

########## 2. reads ###############################################################
# Primary alignments only (-F 0x900); collate pairs by name; keep only complete
# pairs (mates mapped outside the region are dropped together with their pair).
# samtools collate hashes read names, so the FASTQ order is shuffled relative to
# genome position (like a real run) and still deterministic.
log "reads: ${READS_BAM_URL##*/} ${REGION}"
( cd "${TMP}" && samtools view -u -F 0x900 "${READS_BAM_URL}" "${REGION}" ) \
  | samtools collate -u -O -T "${TMP}/collate" - \
  | samtools fastq -n -c 6 \
      -1 "${DATA}/reads/${SAMPLE}_R1.fastq.gz" -2 "${DATA}/reads/${SAMPLE}_R2.fastq.gz" \
      -0 /dev/null -s /dev/null -
n_r1="$(bgzip -dc "${DATA}/reads/${SAMPLE}_R1.fastq.gz" | awk 'END{print NR/4}')"
n_r2="$(bgzip -dc "${DATA}/reads/${SAMPLE}_R2.fastq.gz" | awk 'END{print NR/4}')"
[[ "${n_r1}" == "${n_r2}" ]] || die "R1/R2 record counts differ: ${n_r1} vs ${n_r2}"
log "reads: ${n_r1} pairs (expected depth ~ $(( n_r1 * 2 * 151 / LENGTH ))x)"
source_row "reads/${SAMPLE}_R1.fastq.gz" "${READS_BAM_URL}" "primary alignments in ${REGION}, complete pairs"
source_row "reads/${SAMPLE}_R2.fastq.gz" "${READS_BAM_URL}" "primary alignments in ${REGION}, complete pairs"

########## 3. truth sets ##########################################################
make_truth() {  # make_truth NAME VCF_URL BED_URL
  local name="$1" vcf_url="$2" bed_url="$3"
  log "truth ${name}: ${vcf_url##*/}"
  ( cd "${TMP}" && bcftools view --no-version -r "${REGION}" --regions-overlap pos -Ov "${vcf_url}" ) \
    | python3 "${SHIFT_PY}" vcf - --from-contig "${REGION_CHROM}" --to-contig "${CONTIG}" \
        --shift "${SHIFT}" --keep-start "${REGION_START}" --keep-end "${REGION_END}" \
        --to-length "${LENGTH}" \
    | bgzip -c > "${DATA}/truth/${name}.vcf.gz"
  tabix -f -p vcf "${DATA}/truth/${name}.vcf.gz"
  # Every REF allele must match the mini-reference: catches off-by-one shifts.
  bcftools norm --no-version --check-ref e -f "${DATA}/ref/ref.fa" -Ou \
    "${DATA}/truth/${name}.vcf.gz" -o /dev/null \
    || die "truth ${name}: REF alleles do not match the reference"

  fetch "${bed_url}" "${CACHE}/${bed_url##*/}"
  python3 "${SHIFT_PY}" bed "${CACHE}/${bed_url##*/}" \
      --from-contig "${REGION_CHROM}" --to-contig "${CONTIG}" --shift "${SHIFT}" \
      --keep-start "${BENCH_START}" --keep-end "${BENCH_END}" \
      -o "${DATA}/truth/${name}.bed"
  local n_var bed_bp
  n_var="$(bcftools view -H "${DATA}/truth/${name}.vcf.gz" | wc -l)"
  bed_bp="$(awk '{s+=$3-$2} END{print s+0}' "${DATA}/truth/${name}.bed")"
  log "truth ${name}: ${n_var} variants, benchmark regions ${bed_bp} bp ($(( 100 * bed_bp / LENGTH ))% of region)"
  source_row "truth/${name}.vcf.gz" "${vcf_url}" "GIAB ${name}; ${n_var} records in region"
  source_row "truth/${name}.bed" "${bed_url}" "trimmed by ${EDGE_MARGIN} bp at region ends"
}
make_truth giab_v5.0q  "${TRUTH_V5_VCF}"   "${TRUTH_V5_BED}"
make_truth giab_v4.2.1 "${TRUTH_V421_VCF}" "${TRUTH_V421_BED}"

########## 4. stratifications #####################################################
fetch "${STRAT_BASE}/GRCh38-genome-stratifications-md5s.txt" "${CACHE}/strat-md5s.txt"
: > "${DATA}/strat/strata.tsv"
for entry in "${STRATIFICATIONS[@]}"; do
  name="${entry%%|*}" rel="${entry#*|}"
  md5="$(awk -v f="${rel}" '$2==f {print $1}' "${CACHE}/strat-md5s.txt")"
  [[ -n "${md5}" ]] || die "no md5 for ${rel} in release list"
  fetch "${STRAT_BASE}/${rel}" "${CACHE}/${rel##*/}" "${md5}"
  python3 "${SHIFT_PY}" bed "${CACHE}/${rel##*/}" \
      --from-contig "${REGION_CHROM}" --to-contig "${CONTIG}" --shift "${SHIFT}" \
      --keep-start "${REGION_START}" --keep-end "${REGION_END}" \
      -o "${DATA}/strat/${name}.bed" 2>/dev/null
  bp="$(awk '{s+=$3-$2} END{print s+0}' "${DATA}/strat/${name}.bed")"
  if (( bp == 0 )); then
    log "stratum ${name}: empty in region, skipped"; rm -f "${DATA}/strat/${name}.bed"; continue
  fi
  printf '%s\t%s\n' "${name}" "${name}.bed" >> "${DATA}/strat/strata.tsv"
  log "stratum ${name}: ${bp} bp"
  source_row "strat/${name}.bed" "${STRAT_BASE}/${rel}" "md5 ${md5} verified"
done

########## 5. manifest ############################################################
( cd "${DATA}" && find ref reads truth strat -type f ! -name '*.fai' -print0 | sort -z \
    | xargs -0 sha256sum > MANIFEST.sha256 )
cat > "${DATA}/dataset.json" <<JSON
{
  "sample": "${SAMPLE}",
  "region": "${REGION}",
  "contig": "${CONTIG}",
  "shift": ${SHIFT},
  "length": ${LENGTH},
  "benchmark_window": "${CONTIG}:$((BENCH_START - SHIFT))-$((BENCH_END - SHIFT))",
  "read_pairs": ${n_r1},
  "reference_m5": "${REF_MD5}"
}
JSON
log "done: $(wc -l < "${DATA}/MANIFEST.sha256") files in ${DATA}/MANIFEST.sha256"
