#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
id: bcftools_filter
label: "bcftools norm | filter -> bgzipped, indexed VCF"
doc: |
  1. norm -f ref: left-align and parsimoniously trim indels against the
     reference (the same indel in a homopolymer can be written at several
     positions; comparing with a truth set or merging samples needs one
     canonical form). Multiallelic records are NOT split here: hap.py compares
     genotypes and does its own decomposition.
  2. filter -s LowQual: soft filter (records stay, FILTER is set) so that
     hap.py reports both ALL and PASS rows and the effect of the filter is
     measurable rather than assumed.
       QUAL < min_qual      weak evidence for a non-reference allele
       INFO/DP < min_depth  too few reads for a reliable genotype
       INFO/DP > max_depth  excess depth = likely collapsed repeat / CNV
  Output is BGZF (random access) with a tabix index, written with --no-version.

hints:
  DockerRequirement:
    dockerPull: hg002-mini/tools:1.0.0
  SoftwareRequirement:
    packages:
      bcftools: {version: ["1.25"], specs: ["https://bio.tools/bcftools"]}

requirements:
  InlineJavascriptRequirement: {}
  ResourceRequirement:
    coresMin: 1
    ramMin: 512
  InitialWorkDirRequirement:
    listing:
      - entryname: measure.py
        entry:
          $include: ../../bin/measure.py

inputs:
  calls: File
  reference:
    type: File
    secondaryFiles: [.fai]
  sample: string
  min_qual:
    type: float
    default: 20
  min_depth:
    type: int
    default: 5
  max_depth:
    type: int
    default: 120
    doc: "~3x the expected mean depth (~40x)"

baseCommand: [python3, measure.py]
arguments:
  - {prefix: --step, valueFrom: bcftools_filter}
  - {prefix: --out, valueFrom: bcftools_filter.metrics.json}
  - {prefix: --threads, valueFrom: "1"}
  - "--"
  - bash
  - -euo
  - pipefail
  - -c
  - |
    bcftools norm --no-version -f '$(inputs.reference.path)' --check-ref w -Ou '$(inputs.calls.path)' \
      | bcftools filter --no-version -s LowQual \
          -e 'QUAL<$(inputs.min_qual) || INFO/DP<$(inputs.min_depth) || INFO/DP>$(inputs.max_depth)' \
          -Oz -o '$(inputs.sample).vcf.gz'
    bcftools index --tbi '$(inputs.sample).vcf.gz'

outputs:
  vcf:
    type: File
    format: http://edamontology.org/format_3016  # VCF
    outputBinding: {glob: $(inputs.sample).vcf.gz}
    secondaryFiles: [.tbi]
  metrics:
    type: File
    outputBinding: {glob: bcftools_filter.metrics.json}
