#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
id: strelka2_germline
label: "Strelka2 germline: small variants and gVCF for one sample"
doc: |
  Strelka2 2.9.10 (Kim et al., Nat Methods 2018), the germline caller of
  large Illumina-based population projects, run on the same BAM as bcftools.

  configureStrelkaGermlineWorkflow.py writes a runDir with runWorkflow.py,
  which is then run locally with -j threads. Outputs:
    variants.vcf.gz    variant records, FILTER = PASS or the reason
    genome.vcf.gz      gVCF: variants plus non-variant blocks with GQ
    runStats.tsv       wall time and memory per workflow task
    configure.log      notes of the configure step (e.g. that the error model
                       estimation is switched off on a short contig)
  The reference and BAM are staged and passed by basename, so
  ##reference in the header is not a random staging path. Date and command
  line header lines are removed by strelka2-vcf.cwl. The image runs Python 2.7.

hints:
  DockerRequirement:
    dockerPull: quay.io/biocontainers/strelka@sha256:0fb1a07c38782701c7fe186aad37f0ed18bf94db12f3921430c4b204cacf85e7
  SoftwareRequirement:
    packages:
      strelka: {version: ["2.9.10"], specs: ["https://bio.tools/strelka"]}

requirements:
  InlineJavascriptRequirement: {}
  ResourceRequirement:
    coresMin: $(inputs.threads)
    ramMin: 2048
  InitialWorkDirRequirement:
    listing:
      - entryname: measure.py
        entry:
          $include: ../../bin/measure.py
      - $(inputs.reference)
      - $(inputs.bam)

inputs:
  bam:
    type: File
    secondaryFiles: [.bai]
  reference:
    type: File
    secondaryFiles: [.fai]
  sample: string
  threads:
    type: int
    default: 4

baseCommand: [python, measure.py]
arguments:
  - {prefix: --step, valueFrom: strelka2_germline}
  - {prefix: --out, valueFrom: strelka2_germline.metrics.json}
  - {prefix: --threads, valueFrom: $(inputs.threads)}
  - "--"
  - bash
  - -euo
  - pipefail
  - -c
  - |
    configureStrelkaGermlineWorkflow.py \
        --bam '$(inputs.bam.basename)' \
        --referenceFasta '$(inputs.reference.basename)' \
        --runDir strelka_run > strelka2.configure.log 2>&1
    strelka_run/runWorkflow.py -m local -j $(inputs.threads) --quiet
    mv strelka_run/results/variants/variants.vcf.gz '$(inputs.sample).strelka2.raw.vcf.gz'
    mv strelka_run/results/variants/genome.S1.vcf.gz '$(inputs.sample).strelka2.raw.g.vcf.gz'
    mv strelka_run/results/stats/runStats.tsv strelka2.runStats.tsv
    rm -rf strelka_run

outputs:
  vcf:
    type: File
    outputBinding: {glob: $(inputs.sample).strelka2.raw.vcf.gz}
  gvcf:
    type: File
    outputBinding: {glob: $(inputs.sample).strelka2.raw.g.vcf.gz}
  run_stats:
    type: File
    outputBinding: {glob: strelka2.runStats.tsv}
  configure_log:
    type: File
    outputBinding: {glob: strelka2.configure.log}
  metrics:
    type: File
    outputBinding: {glob: strelka2_germline.metrics.json}
