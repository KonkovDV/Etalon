#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
id: samtools_markdup
label: "samtools markdup + index"
doc: |
  Marks (does not remove) PCR and optical duplicates.

  -d 2500: optical-duplicate distance for patterned flow cells (NovaSeq,
  HiSeq X). On patterned flow cells a cluster can seed a neighbouring nanowell
  ("pad hopping"), giving duplicates thousands of pixels apart; 100 px, the
  classic value for random flow cells, misses them. Optical duplicates are a
  property of the instrument, PCR duplicates of the library: the JSON keeps
  them apart. For a PCR-free library almost all duplicates should be optical.

  The index is written in the same pass (##idx## syntax of htslib).

$namespaces:
  edam: http://edamontology.org/

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
    ramMin: 2048
  InitialWorkDirRequirement:
    listing:
      - entryname: measure.py
        entry:
          $include: ../../bin/measure.py

inputs:
  sorted_bam:
    type: File
    format: edam:format_2572
  sample: string
  optical_distance:
    type: int
    default: 2500
  threads:
    type: int
    default: 4

baseCommand: [python3, measure.py]
arguments:
  - {prefix: --step, valueFrom: samtools_markdup}
  - {prefix: --out, valueFrom: samtools_markdup.metrics.json}
  - {prefix: --threads, valueFrom: $(inputs.threads)}
  - "--"
  - samtools
  - markdup
  - --no-PG
  - {prefix: -@, valueFrom: $(inputs.threads)}
  - {prefix: -d, valueFrom: $(inputs.optical_distance)}
  - --json
  - {prefix: -f, valueFrom: $(inputs.sample).markdup.json}
  - {prefix: -T, valueFrom: $(runtime.tmpdir)/markdup}
  - --write-index
  - $(inputs.sorted_bam.path)
  - $(inputs.sample).bam##idx##$(inputs.sample).bam.bai

outputs:
  bam:
    type: File
    format: edam:format_2572
    outputBinding: {glob: $(inputs.sample).bam}
    secondaryFiles: [.bai]
  markdup_json:
    type: File
    outputBinding: {glob: $(inputs.sample).markdup.json}
  metrics:
    type: File
    outputBinding: {glob: samtools_markdup.metrics.json}
