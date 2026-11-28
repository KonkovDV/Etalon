#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
id: bcftools_stats
label: "bcftools stats (PASS calls)"
doc: |
  Call-set statistics independent of any truth set: Ti/Tv (expected ~2.0-2.1
  for whole-genome SNVs, ~3 in exons; a low value means many false
  positives, which are close to random: Ti/Tv 0.5), the substitution spectrum
  (an excess of C>A/G>T points to 8-oxoG oxidative damage during library
  preparation), indel length distribution and per-sample het/hom counts.

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
  vcf:
    type: File
    secondaryFiles: [.tbi]
  reference:
    type: File
    secondaryFiles: [.fai]
  sample: string

baseCommand: [python3, measure.py]
arguments:
  - {prefix: --step, valueFrom: bcftools_stats}
  - {prefix: --out, valueFrom: bcftools_stats.metrics.json}
  - {prefix: --threads, valueFrom: "1"}
  - "--"
  - bash
  - -euo
  - pipefail
  - -c
  - |
    bcftools stats -f PASS -F '$(inputs.reference.path)' -s - '$(inputs.vcf.path)' \
      > '$(inputs.sample).bcftools_stats.txt'

outputs:
  stats:
    type: File
    outputBinding: {glob: $(inputs.sample).bcftools_stats.txt}
  metrics:
    type: File
    outputBinding: {glob: bcftools_stats.metrics.json}
