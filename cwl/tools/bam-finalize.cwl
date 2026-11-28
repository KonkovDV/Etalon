#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
id: bam_finalize
label: "Re-block a BAM with htslib and index it"
doc: |
  STAR's coordinate-sorted BAM has the same records and header on every run, but
  not the same bytes: STAR compresses each sorting bin on its own, and the bin
  boundaries come from the alignments of whichever thread first fills its buffer
  (BAMoutput::coordBins in STAR 2.7.11b). The decompressed stream is identical,
  only the BGZF block boundaries move (docs/DEBUGGING.md, D-20).

  samtools view -b writes the same stream again in htslib's fixed 64 KiB blocks,
  so the file is byte-identical between runs with the same thread count, as the
  WGS BAM is. --no-PG keeps the header exactly as STAR wrote it. The index is
  for viewers and region queries.

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
    ramMin: 512
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

baseCommand: [python3, measure.py]
arguments:
  - {prefix: --step, valueFrom: "bam_finalize_$(inputs.sample)"}
  - {prefix: --out, valueFrom: "bam_finalize_$(inputs.sample).metrics.json"}
  - {prefix: --threads, valueFrom: $(inputs.threads)}
  - "--"
  - bash
  - -euo
  - pipefail
  - -c
  - |
    samtools view --no-PG -b -@ $(inputs.threads) -o '$(inputs.sample).bam' '$(inputs.bam.path)'
    samtools index -@ $(inputs.threads) '$(inputs.sample).bam'

outputs:
  bam_indexed:
    type: File
    format: edam:format_2572
    secondaryFiles: [.bai]
    outputBinding: {glob: $(inputs.sample).bam}
  metrics:
    type: File
    outputBinding: {glob: "bam_finalize_$(inputs.sample).metrics.json"}
