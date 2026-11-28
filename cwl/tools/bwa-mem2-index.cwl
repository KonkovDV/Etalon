#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
id: bwa_mem2_index
label: "bwa-mem2 index + samtools faidx"
doc: |
  Builds the bwa-mem2 FM-index and the .fai index for a FASTA reference and
  returns the FASTA with every index as secondaryFiles, so downstream steps
  declare exactly which index they need.

  For a full GRCh38 the index (~10 GB RAM, ~1 h) is built once and passed in
  as a prebuilt input instead; for the 2 Mb mini-reference it takes seconds.

$namespaces:
  edam: http://edamontology.org/

hints:
  DockerRequirement:
    dockerPull: hg002-mini/tools:1.0.0
  SoftwareRequirement:
    packages:
      bwa-mem2: {version: ["2.3"], specs: ["https://bio.tools/bwa-mem2"]}
      samtools: {version: ["1.25"], specs: ["https://bio.tools/samtools"]}

requirements:
  InlineJavascriptRequirement: {}
  ResourceRequirement:
    coresMin: 1
    ramMin: 2048
  InitialWorkDirRequirement:
    listing:
      - entryname: measure.py
        entry:
          $include: ../../bin/measure.py
      - entry: $(inputs.reference)
        writable: false

inputs:
  reference:
    type: File
    format: edam:format_1929  # FASTA

baseCommand: [python3, measure.py]
arguments:
  - {prefix: --step, valueFrom: bwa_mem2_index}
  - {prefix: --out, valueFrom: bwa_mem2_index.metrics.json}
  - {prefix: --threads, valueFrom: "1"}
  - "--"
  - bash
  - -euo
  - pipefail
  - -c
  - |
    bwa-mem2 index '$(inputs.reference.basename)'
    samtools faidx '$(inputs.reference.basename)'

outputs:
  indexed_reference:
    type: File
    format: edam:format_1929
    outputBinding: {glob: $(inputs.reference.basename)}
    secondaryFiles:
      - .fai
      - ".0123"
      - .amb
      - .ann
      - .bwt.2bit.64
      - .pac
  metrics:
    type: File
    outputBinding: {glob: bwa_mem2_index.metrics.json}
