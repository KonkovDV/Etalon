#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
id: bcftools_call
label: "bcftools mpileup | call (multiallelic caller)"
doc: |
  Germline SNV/indel calling for one diploid sample.

  mpileup
    -X illumina   bcftools >= 1.20 profile for short reads: switches on the
                  consensus-based indel caller (--indels-cns) and a longer
                  indel window (--indel-size 110). Set `mpileup_profile` to
                  "illumina-1.18" (or "") to compare against the older model.
    -q 20 / -Q 20 minimum mapping / base quality. With NovaSeq binned qualities
                  (Q2/11/25/37) -Q 20 drops exactly the two lowest bins.
    -a ...        FORMAT/AD and DP are needed for allele-balance filters later
                  and for population-database style aggregation.
    --max-depth   a cap per file; at ~40x mean depth, 500 is never reached in
                  unique sequence, so it only limits collapsed repeats.
  call
    -m            multiallelic caller (default prior -P 1.1e-3, the expected
                  heterozygosity of the human genome, theta ~ 1e-3)
    -v            variant sites only
  --no-version on both: the VCF header then carries no command lines with
  random staging paths, which is required for a byte-identical VCF.
  For the same reason the reference and BAM are staged into the working
  directory and passed by basename: mpileup writes ##reference=file://<path>
  into the header (docs/DEBUGGING.md, D-08).

hints:
  DockerRequirement:
    dockerPull: hg002-mini/tools:1.0.0
  SoftwareRequirement:
    packages:
      bcftools: {version: ["1.25"], specs: ["https://bio.tools/bcftools"]}

requirements:
  InlineJavascriptRequirement: {}
  ResourceRequirement:
    coresMin: 2
    ramMin: 1024
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
  mpileup_profile:
    type: string
    default: "illumina"
    doc: "bcftools mpileup -X profile; empty string = bcftools defaults"
  min_mapq:
    type: int
    default: 20
  min_baseq:
    type: int
    default: 20
  max_depth:
    type: int
    default: 500

baseCommand: [python3, measure.py]
arguments:
  - {prefix: --step, valueFrom: bcftools_call}
  - {prefix: --out, valueFrom: bcftools_call.metrics.json}
  - {prefix: --threads, valueFrom: "2"}
  - "--"
  - bash
  - -euo
  - pipefail
  - -c
  - |
    bcftools mpileup --no-version \
        $(inputs.mpileup_profile ? "-X " + inputs.mpileup_profile : "") \
        -f '$(inputs.reference.basename)' \
        -q $(inputs.min_mapq) -Q $(inputs.min_baseq) --max-depth $(inputs.max_depth) \
        -a FORMAT/AD,FORMAT/DP,FORMAT/SP,INFO/AD \
        -Ou '$(inputs.bam.basename)' \
      | bcftools call --no-version -m -v -Ob -o '$(inputs.sample).calls.bcf'

outputs:
  calls:
    type: File
    outputBinding: {glob: $(inputs.sample).calls.bcf}
  metrics:
    type: File
    outputBinding: {glob: bcftools_call.metrics.json}
