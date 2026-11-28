#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
id: samtools_sort
label: "samtools sort (coordinate)"
doc: |
  Coordinate sort. Memory = threads x per-thread buffer (-m) plus overhead,
  which is why ramMin is computed from both. --no-PG keeps the header free of
  run-specific paths (cwltool stages inputs under random directories), so the
  BAM header is identical between runs.

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
    ramMin: $(inputs.threads * inputs.mem_per_thread_mb + 512)
  InitialWorkDirRequirement:
    listing:
      - entryname: measure.py
        entry:
          $include: ../../bin/measure.py

inputs:
  bam:
    type: File
    format: edam:format_2572
  sample: string
  threads:
    type: int
    default: 4
  mem_per_thread_mb:
    type: int
    default: 512

baseCommand: [python3, measure.py]
arguments:
  - {prefix: --step, valueFrom: samtools_sort}
  - {prefix: --out, valueFrom: samtools_sort.metrics.json}
  - {prefix: --threads, valueFrom: $(inputs.threads)}
  - "--"
  - samtools
  - sort
  - --no-PG
  - {prefix: -@, valueFrom: $(inputs.threads)}
  - {prefix: -m, valueFrom: $(inputs.mem_per_thread_mb)M}
  - {prefix: -T, valueFrom: $(runtime.tmpdir)/sort}
  - {prefix: -o, valueFrom: $(inputs.sample).sorted.bam}
  - $(inputs.bam.path)

outputs:
  sorted_bam:
    type: File
    format: edam:format_2572
    outputBinding: {glob: $(inputs.sample).sorted.bam}
  metrics:
    type: File
    outputBinding: {glob: samtools_sort.metrics.json}
