#!/usr/bin/env bash
# Does fastp's insert-size histogram depend on the thread count?
#
#   scripts/check_fastp_isize.sh [REPORT]        # default: results/fastp_isize_threads.md
#
# Runs three fastp 1.4.0 binaries on the same read pairs with 1-4 worker threads:
#   official   the release binary of the tools image (opengene.org, sha256-pinned)
#   release    built from tag v1.4.0 (image hg002-mini/fastp-isize:1.4.0)
#   patched    the same source + docker/fastp-isize/fastp-1.4.0-isize-all-threads.patch
# and records, per run: pairs that entered the histogram, its peak, a hash of the
# histogram and an md5 of the trimmed reads (decompressed, so gzip settings do not
# matter). In fastp 1.4.0 only worker thread 0 evaluates the insert size
# (src/peprocessor.cpp), so with N threads ~1/N of the packs enter the histogram
# (docs/DEBUGGING.md, D-23). Needs: make image, make fastp-isize-image, the data of
# make data and make rnaseq-data.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="${TOOLS_IMAGE:-hg002-mini/tools:1.0.0}"
FASTP_ISIZE="${FASTP_ISIZE_IMAGE:-hg002-mini/fastp-isize:1.4.0}"
REPORT="${1:-${ROOT}/results/fastp_isize_threads.md}"
THREADS=(1 2 3 4)
# name|reads dir|R1|R2
DATASETS=(
  "RNA-seq UHR_Rep1|data/rnaseq/reads|UHR_Rep1_R1.fastq.gz|UHR_Rep1_R2.fastq.gz"
  "WGS HG002|data/reads|HG002_R1.fastq.gz|HG002_R2.fastq.gz"
)
OUT="$(mktemp -d "${ROOT}/results/.fastp_isize.XXXXXX")"
trap 'rm -rf "${OUT}"' EXIT

run() {  # run IMAGE BINARY READS_DIR R1 R2 THREADS TAG
  docker run --rm -u "$(id -u):$(id -g)" -v "${ROOT}/$3:/r:ro" -v "${OUT}:/o" "$1" \
    "$2" --in1 "/r/$4" --in2 "/r/$5" --out1 "/o/$7.R1.fq.gz" --out2 "/o/$7.R2.fq.gz" \
    --trim_poly_g --thread "$6" --compression 4 --json "/o/$7.json" --html "/o/$7.html" 2>/dev/null
}

for entry in "${DATASETS[@]}"; do
  IFS='|' read -r name dir r1 r2 <<< "${entry}"
  [[ -s "${ROOT}/${dir}/${r1}" ]] || { echo "missing ${dir}/${r1}: run make data / make rnaseq-data" >&2; exit 2; }
  tag="${name// /_}"
  for t in "${THREADS[@]}"; do
    run "${TOOLS}" fastp "${dir}" "${r1}" "${r2}" "${t}" "${tag}.official.t${t}"
    run "${FASTP_ISIZE}" fastp.release "${dir}" "${r1}" "${r2}" "${t}" "${tag}.release.t${t}"
    run "${FASTP_ISIZE}" fastp.patched "${dir}" "${r1}" "${r2}" "${t}" "${tag}.patched.t${t}"
  done
done

mkdir -p "$(dirname "${REPORT}")"
python3 - "${OUT}" "${REPORT}" "${THREADS[@]}" -- "${DATASETS[@]}" <<'PY'
import gzip, hashlib, json, sys

out, report = sys.argv[1], sys.argv[2]
sep = sys.argv.index("--")
threads = [int(t) for t in sys.argv[3:sep]]
datasets = [d.split("|")[0] for d in sys.argv[sep + 1:]]
lines = [
    "# fastp 1.4.0: длина вставки и число потоков",
    "",
    "Одни и те же пары ридов, три сборки fastp 1.4.0 и 1–4 рабочих потока. «Пар в гистограмме» — сколько пар",
    "вошло в гистограмму длины вставки (вместе с неопределёнными), «риды» — md5 распакованных R1 и R2 после fastp.",
    "Создаётся `scripts/check_fastp_isize.sh`.",
    "",
]
for ds in datasets:
    tag = ds.replace(" ", "_")
    lines += ["## " + ds, "", "| сборка | потоков | пар после фильтров | пар в гистограмме | пик | гистограмма | риды |", "|---|---|---|---|---|---|---|"]
    for build in ("official", "release", "patched"):
        for t in threads:
            stem = "%s/%s.%s.t%d" % (out, tag, build, t)
            js = json.load(open(stem + ".json"))
            isz = js["insert_size"]
            hist = isz["histogram"] + [isz["unknown"]]
            reads = hashlib.md5()
            for r in ("R1", "R2"):
                with gzip.open("%s.%s.fq.gz" % (stem, r)) as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        reads.update(chunk)
            lines.append(
                "| %s | %d | %d | %d | %d | `%s` | `%s` |"
                % (
                    build,
                    t,
                    js["summary"]["after_filtering"]["total_reads"] // 2,
                    sum(hist),
                    isz["peak"],
                    hashlib.sha256(json.dumps(hist).encode()).hexdigest()[:12],
                    reads.hexdigest()[:12],
                )
            )
    lines.append("")
open(report, "w", encoding="utf-8").write("\n".join(lines))
print("report: " + report, file=sys.stderr)
PY
