#!/usr/bin/env bash
# Build the RNA-seq mini-dataset: UHR and HBR (three replicates each) with ERCC
# spike-in mixes, a chr22 + ERCC92 reference with its annotation, and the ERCC
# concentration table, which is the truth set of the RNA-seq workflow.
#
#   scripts/prepare_rnaseq_data.sh      # uses config/rnaseq.env; `make rnaseq-data` runs it in the tools image
#
# Needs: samtools, python3, curl, tar, gzip (all in the tools image).
#
# Result (data/rnaseq/):
#   reads/<group>_Rep<n>_R{1,2}.fastq.gz     raw paired reads, 6 samples
#   ref/chr22_ERCC92.fa(.fai)                 GRCh38 chr22 + 92 ERCC sequences
#   ref/chr22_ERCC92.gtf                      GENCODE v50 chr22 + ERCC92 annotation
#   truth/ercc_concentrations.tsv             attomol/ul of each ERCC in Mix 1 and Mix 2
#   samples.tsv, dataset.json                 sample sheet and summary
#   MANIFEST.sha256, SOURCES.tsv              checksums and provenance
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"
# shellcheck source=../config/rnaseq.env
source "${ROOT}/config/rnaseq.env"

log() { printf '[prepare_rnaseq %(%H:%M:%S)T] %s\n' -1 "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

for tool in samtools python3 curl tar gzip; do
  command -v "${tool}" >/dev/null || die "${tool} not found in PATH (run via 'make rnaseq-data')"
done

mkdir -p "${RNASEQ_DIR}"/{reads,ref,truth} "${RNASEQ_CACHE}"
DIR="$(cd "${RNASEQ_DIR}" && pwd)"
CACHE="$(cd "${RNASEQ_CACHE}" && pwd)"
TMP="$(mktemp -d "${DIR}/.tmp.XXXXXX")"
trap 'rm -rf "${TMP}"' EXIT

printf 'file\tsource\tnote\n' > "${DIR}/SOURCES.tsv"
source_row() { printf '%s\t%s\t%s\n' "$1" "$2" "$3" >> "${DIR}/SOURCES.tsv"; }

fetch() {  # fetch URL DEST ALGO SUM; cached, retried, checksum-verified
  local url="$1" dest="$2" algo="$3" sum="$4"
  if [[ ! -s "${dest}" ]]; then
    log "download ${url##*/}"
    curl -fsSL --retry 5 --retry-delay 5 -o "${dest}.part" "${url}"
    mv "${dest}.part" "${dest}"
  fi
  echo "${sum}  ${dest}" | "${algo}sum" -c --quiet - || die "${algo} mismatch: ${dest}"
}

########## 1. reads ##############################################################
fetch "${RNASEQ_READS_URL}" "${CACHE}/${RNASEQ_READS_URL##*/}" sha256 "${RNASEQ_READS_SHA256}"
tar -xf "${CACHE}/${RNASEQ_READS_URL##*/}" -C "${TMP}"
printf 'sample\tgroup\treplicate\tercc_mix\treads_1\treads_2\tpairs\n' > "${DIR}/samples.tsv"
for entry in "${RNASEQ_SAMPLES[@]}"; do
  IFS='|' read -r group rep mix <<< "${entry}"
  sample="${group}_Rep${rep}"
  for r in 1 2; do
    src="${TMP}/${group}_Rep${rep}_ERCC-${mix}_Build37-ErccTranscripts-chr22.read${r}.fastq.gz"
    [[ -s "${src}" ]] || die "missing in archive: ${src##*/}"
    mv "${src}" "${DIR}/reads/${sample}_R${r}.fastq.gz"
    source_row "reads/${sample}_R${r}.fastq.gz" "${RNASEQ_READS_URL}" "${src##*/}"
  done
  # pairs: same count, same read names in the same order (/1 and /2 suffixes aside)
  pairs="$(python3 - "${DIR}/reads/${sample}_R1.fastq.gz" "${DIR}/reads/${sample}_R2.fastq.gz" <<'PY'
import gzip, sys
def names(path):
    with gzip.open(path, "rt") as fh:
        for i, line in enumerate(fh):
            if i % 4 == 0:
                yield line.split()[0].rsplit("/", 1)[0]
n = 0
for a, b in zip(names(sys.argv[1]), names(sys.argv[2])):
    if a != b:
        sys.exit("read %d: %s != %s" % (n + 1, a, b))
    n += 1
print(n)
PY
)" || die "${sample}: R1 and R2 do not pair up"
  printf '%s\t%s\t%s\t%s\treads/%s_R1.fastq.gz\treads/%s_R2.fastq.gz\t%s\n' \
    "${sample}" "${group}" "${rep}" "${mix}" "${sample}" "${sample}" "${pairs}" >> "${DIR}/samples.tsv"
  log "reads ${sample} (ERCC ${mix}): ${pairs} pairs"
done

########## 2. ERCC truth and sequences ##############################################
fetch "${ERCC_TABLE_URL}" "${CACHE}/${ERCC_TABLE_URL##*/}" sha256 "${ERCC_TABLE_SHA256}"
tr -d '\r' < "${CACHE}/${ERCC_TABLE_URL##*/}" > "${DIR}/truth/ercc_concentrations.tsv"
fetch "${ERCC_ZIP_URL}" "${CACHE}/${ERCC_ZIP_URL##*/}" sha256 "${ERCC_ZIP_SHA256}"
python3 -m zipfile -e "${CACHE}/${ERCC_ZIP_URL##*/}" "${TMP}/ercc"
# The table must describe exactly the 92 sequences: 4 subgroups x 23, and the ratio
# column must agree with the two concentration columns.
python3 - "${DIR}/truth/ercc_concentrations.tsv" "${TMP}/ercc/ERCC92.fa" "${TMP}/ercc/ERCC92.gtf" <<'PY'
import collections, csv, math, sys
rows = list(csv.reader(open(sys.argv[1]), delimiter="\t"))[1:]
ids = {r[1] for r in rows}
groups = collections.Counter(r[2] for r in rows)
assert len(rows) == 92 and len(ids) == 92, "expected 92 ERCC rows"
assert groups == {"A": 23, "B": 23, "C": 23, "D": 23}, groups
for r in rows:
    ratio = float(r[3]) / float(r[4])
    assert abs(ratio - float(r[5])) < 0.01, r
    assert abs(math.log2(ratio) - float(r[6])) < 0.01, r
fa = {line[1:].split()[0] for line in open(sys.argv[2]) if line.startswith(">")}
gtf = {line.split("\t")[0] for line in open(sys.argv[3]) if line.strip()}
assert fa == ids == gtf, "ERCC ids differ between table, FASTA and GTF"
print("ERCC truth: 92 transcripts, subgroups %s" % dict(sorted(groups.items())), file=sys.stderr)
PY
source_row truth/ercc_concentrations.tsv "${ERCC_TABLE_URL}" "Thermo Fisher ERCC Controls Analysis; CR removed"

########## 3. chr22 of GRCh38 ######################################################
log "genome: ${RNASEQ_CHROM} from ${RNASEQ_GENOME_URL##*/}"
( cd "${TMP}" && samtools faidx "${RNASEQ_GENOME_URL}" "${RNASEQ_CHROM}" ) > "${TMP}/chrom.raw.fa"
fetch_dict() { curl -fsSL --retry 3 "${RNASEQ_DICT_URL}"; }
expect="$(fetch_dict | awk -v sn="SN:${RNASEQ_CHROM}" '$2 == sn {for (i = 3; i <= NF; i++) if ($i ~ /^(LN|M5):/) printf "%s ", $i}')"
[[ -n "${expect}" ]] || die "${RNASEQ_CHROM} not found in ${RNASEQ_DICT_URL##*/}"
# One FASTA for STAR and samtools: chr22 at 60 bp per line, then the ERCC sequences.
python3 - "${TMP}/chrom.raw.fa" "${TMP}/ercc/ERCC92.fa" "${DIR}/ref/chr22_ERCC92.fa" "${expect}" <<'PY'
import hashlib, sys
def read(path):
    name, seq, out = None, [], []
    for line in open(path):
        line = line.strip()
        if line.startswith(">"):
            if name:
                out.append((name, "".join(seq)))
            name, seq = line[1:].split()[0], []
        elif line:
            seq.append(line)
    out.append((name, "".join(seq)))
    return out
chrom = read(sys.argv[1])
ercc = read(sys.argv[2])
name, seq = chrom[0]
got = "LN:%d M5:%s" % (len(seq), hashlib.md5(seq.upper().encode()).hexdigest())
want = sys.argv[4].strip()
if got != want:
    sys.exit("%s: %s, Broad dictionary says %s" % (name, got, want))
print("%s matches the Broad GRCh38 dictionary: %s" % (name, got), file=sys.stderr)
with open(sys.argv[3], "w") as out:
    for n, s in chrom + ercc:
        out.write(">%s\n" % n)
        for i in range(0, len(s), 60):
            out.write(s[i:i + 60] + "\n")
PY
samtools faidx "${DIR}/ref/chr22_ERCC92.fa"
source_row ref/chr22_ERCC92.fa "${RNASEQ_GENOME_URL}" "${RNASEQ_CHROM} (${expect% }) + ERCC92.fa from ${ERCC_ZIP_URL##*/}"

########## 4. annotation ############################################################
fetch "${RNASEQ_GTF_URL}" "${CACHE}/${RNASEQ_GTF_URL##*/}" md5 "${RNASEQ_GTF_MD5}"
{
  gzip -dc "${CACHE}/${RNASEQ_GTF_URL##*/}" | awk -F'\t' -v c="${RNASEQ_CHROM}" '/^#/ || $1 == c'
  # ERCC92.gtf has gene_id and transcript_id only; gene_name/gene_type make the
  # spike-ins look like any other gene to featureCounts and the report.
  awk -F'\t' -v OFS='\t' '{sub(/;?[ ]*$/, "", $9); $9 = $9 "; gene_name \"" $1 "\"; gene_type \"ERCC\";"; print}' \
    "${TMP}/ercc/ERCC92.gtf"
} > "${DIR}/ref/chr22_ERCC92.gtf"
python3 - "${DIR}/ref/chr22_ERCC92.gtf" "${DIR}/ref/chr22_ERCC92.fa.fai" <<'PY'
import collections, sys
contigs = {line.split("\t")[0] for line in open(sys.argv[2])}
seen, genes = set(), collections.Counter()
for line in open(sys.argv[1]):
    if line.startswith("#"):
        continue
    f = line.rstrip("\n").split("\t")
    seen.add(f[0])
    if f[2] == "gene" or (f[1] == "ERCC" and f[2] == "exon"):
        genes["ERCC" if f[1] == "ERCC" else "chr22"] += 1
missing = seen - contigs
assert not missing, "GTF contigs absent from the FASTA: %s" % sorted(missing)
print("annotation: %d chr22 genes, %d ERCC" % (genes["chr22"], genes["ERCC"]), file=sys.stderr)
PY
source_row ref/chr22_ERCC92.gtf "${RNASEQ_GTF_URL}" "${RNASEQ_CHROM} records + ERCC92.gtf with gene_name/gene_type added"

########## 5. manifest ##############################################################
( cd "${DIR}" && find reads ref truth samples.tsv -type f ! -name '*.fai' -print0 | sort -z \
    | xargs -0 sha256sum > MANIFEST.sha256 )
python3 - "${DIR}" <<'PY'
import csv, json, os, sys
d = sys.argv[1]
samples = list(csv.DictReader(open(os.path.join(d, "samples.tsv")), delimiter="\t"))
json.dump(
    {
        "samples": [s["sample"] for s in samples],
        "read_pairs": {s["sample"]: int(s["pairs"]) for s in samples},
        "ercc_mix": {s["sample"]: s["ercc_mix"] for s in samples},
        "reference_contigs": sum(1 for _ in open(os.path.join(d, "ref", "chr22_ERCC92.fa.fai"))),
    },
    open(os.path.join(d, "dataset.json"), "w"),
    indent=2,
    sort_keys=True,
)
PY
log "done: $(wc -l < "${DIR}/MANIFEST.sha256") files in ${DIR}/MANIFEST.sha256"
