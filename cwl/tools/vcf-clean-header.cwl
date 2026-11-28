#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
id: vcf_clean_header
label: "Drop run-specific header lines from a caller's VCF, recompress, index"
doc: |
  Third-party callers write the run date, start time, command line and the
  reference path into the VCF header (Strelka2: ##fileDate, ##startTime,
  ##cmdline, ##reference; DeepVariant: ##DeepVariant_version only). These
  differ between two otherwise identical runs, so the file could never be
  byte-identical (docs/DEBUGGING.md, D-08). This step removes exactly those
  header lines with bcftools reheader, rewrites the file with
  `bcftools view --no-version` (no records change) and indexes it.

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
  vcf: File
  out_name:
    type: string
    doc: "output file name, e.g. HG002.strelka2.vcf.gz"
  step_name:
    type: string
    default: vcf_clean_header
  drop_lines:
    type: string
    default: "fileDate|startTime|cmdline|reference"
    doc: "header keys to drop, as an extended regular expression alternation"

baseCommand: [python3, measure.py]
arguments:
  - {prefix: --step, valueFrom: $(inputs.step_name)}
  - {prefix: --out, valueFrom: $(inputs.step_name).metrics.json}
  - {prefix: --threads, valueFrom: "1"}
  - "--"
  - bash
  - -euo
  - pipefail
  - -c
  - |
    bcftools view --no-version -h '$(inputs.vcf.path)' | grep -v -E '^##($(inputs.drop_lines))=' > header.txt
    bcftools reheader -h header.txt '$(inputs.vcf.path)' \
      | bcftools view --no-version -Oz -o '$(inputs.out_name)'
    bcftools index --tbi '$(inputs.out_name)'
    rm header.txt

outputs:
  out:
    type: File
    outputBinding: {glob: $(inputs.out_name)}
    secondaryFiles: [.tbi]
  metrics:
    type: File
    outputBinding: {glob: $(inputs.step_name).metrics.json}
