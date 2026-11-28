#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
id: happy
label: "hap.py: compare calls with a GIAB truth set (GA4GH benchmarking)"
doc: |
  Haplotype-aware comparison of the query VCF with a truth VCF inside the
  truth set's confident regions (GA4GH small-variant benchmarking standard,
  Krusche et al., Nat Biotechnol 2019).

  Matching is done on haplotypes, not on VCF text, so differently written but
  equivalent indels count as matches. Outputs:
    <name>.summary.csv    SNP/INDEL x ALL/PASS: TP, FN, FP, recall, precision, F1
    <name>.extended.csv   the same per stratification region and variant subtype
    <name>.vcf.gz         every truth/query record labelled TP/FP/FN (BD/BK tags)
    <name>.roc.*.csv.gz   precision-recall curves over QUAL
  Engine: xcmp (hap.py's own, default). The image is the biocontainers build,
  pinned by digest. It runs Python 2.7, which is why measure.py is 2/3-compatible.

hints:
  DockerRequirement:
    dockerPull: quay.io/biocontainers/hap.py@sha256:d63b963a6cb01b4830393b22369e7b91d298e4156dde353739e74e4cfa4f96d0
  SoftwareRequirement:
    packages:
      hap.py: {version: ["0.3.15"], specs: ["https://bio.tools/hap.py"]}

requirements:
  InlineJavascriptRequirement: {}
  ResourceRequirement:
    coresMin: $(inputs.threads)
    ramMin: 4096
  InitialWorkDirRequirement:
    listing:
      - entryname: measure.py
        entry:
          $include: ../../bin/measure.py

inputs:
  truth_name:
    type: string
    doc: "label used as output prefix, e.g. giab_v5.0q"
  truth_vcf:
    type: File
    secondaryFiles: [.tbi]
  truth_bed: File
  query_vcf:
    type: File
    secondaryFiles: [.tbi]
  reference:
    type: File
    secondaryFiles: [.fai]
  stratification:
    type: Directory?
    doc: "directory with strata.tsv (name<TAB>file.bed) and the BED files"
  engine:
    type: string
    default: "xcmp"
  threads:
    type: int
    default: 4

baseCommand: [python, measure.py]
arguments:
  - {prefix: --step, valueFrom: "happy_$(inputs.truth_name)"}
  - {prefix: --out, valueFrom: "happy_$(inputs.truth_name).metrics.json"}
  - {prefix: --threads, valueFrom: $(inputs.threads)}
  - "--"
  - hap.py
  - $(inputs.truth_vcf.path)
  - $(inputs.query_vcf.path)
  - {prefix: -f, valueFrom: $(inputs.truth_bed.path)}
  - {prefix: -r, valueFrom: $(inputs.reference.path)}
  - {prefix: -o, valueFrom: $(inputs.truth_name)}
  - {prefix: --engine, valueFrom: $(inputs.engine)}
  - {prefix: --threads, valueFrom: $(inputs.threads)}
  - {prefix: --scratch-prefix, valueFrom: $(runtime.tmpdir)}
  - valueFrom: '${ return inputs.stratification ? ["--stratification", inputs.stratification.path + "/strata.tsv"] : []; }'

outputs:
  summary:
    type: File
    outputBinding: {glob: $(inputs.truth_name).summary.csv}
  extended:
    type: File
    outputBinding: {glob: $(inputs.truth_name).extended.csv}
  annotated_vcf:
    type: File
    outputBinding: {glob: $(inputs.truth_name).vcf.gz}
    secondaryFiles: [.tbi]
  metrics_json:
    type: File
    outputBinding: {glob: $(inputs.truth_name).metrics.json.gz}
  runinfo:
    type: File
    outputBinding: {glob: $(inputs.truth_name).runinfo.json}
  roc_all:
    type: File
    outputBinding: {glob: $(inputs.truth_name).roc.all.csv.gz}
  metrics:
    type: File
    outputBinding: {glob: happy_$(inputs.truth_name).metrics.json}
