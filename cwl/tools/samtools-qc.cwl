#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
id: samtools_qc
label: "samtools flagstat / stats / coverage"
doc: |
  Alignment QC used by the report: mapping and pairing rates (flagstat, JSON),
  error rate, insert size and the per-base coverage histogram (stats; COV lines
  are used to test the depth distribution against a Poisson model), and mean
  depth / breadth per contig (coverage).

  `samtools stats -d` excludes duplicate-flagged reads, as `samtools coverage`
  and bcftools mpileup do by default: all three then describe the same reads.
  Without -d the depth histogram counted duplicates (mean 38.6x) while
  coverage reported 34.5x (docs/DEBUGGING.md, D-07).

hints:
  DockerRequirement:
    dockerPull: hg002-mini/tools:1.0.0
  SoftwareRequirement:
    packages:
      samtools: {version: ["1.25"], specs: ["https://bio.tools/samtools"]}

requirements:
  InlineJavascriptRequirement: {}
  ResourceRequirement:
    coresMin: $(inputs.threads)
    ramMin: 1024
  InitialWorkDirRequirement:
    listing:
      - entryname: measure.py
        entry:
          $include: ../../bin/measure.py

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

baseCommand: [python3, measure.py]
arguments:
  - {prefix: --step, valueFrom: samtools_qc}
  - {prefix: --out, valueFrom: samtools_qc.metrics.json}
  - {prefix: --threads, valueFrom: $(inputs.threads)}
  - "--"
  - bash
  - -euo
  - pipefail
  - -c
  - |
    samtools flagstat -@ $(inputs.threads) -O json '$(inputs.bam.path)' > '$(inputs.sample).flagstat.json'
    samtools stats -d -@ $(inputs.threads) --reference '$(inputs.reference.path)' --coverage 1,1000,1 \
        '$(inputs.bam.path)' > '$(inputs.sample).samtools_stats.txt'
    samtools coverage '$(inputs.bam.path)' > '$(inputs.sample).coverage.tsv'

outputs:
  flagstat:
    type: File
    outputBinding: {glob: $(inputs.sample).flagstat.json}
  stats:
    type: File
    outputBinding: {glob: $(inputs.sample).samtools_stats.txt}
  coverage:
    type: File
    outputBinding: {glob: $(inputs.sample).coverage.tsv}
  metrics:
    type: File
    outputBinding: {glob: samtools_qc.metrics.json}
