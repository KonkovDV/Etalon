#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
id: featurecounts
label: "featureCounts: fragments per gene for all samples in one table"
doc: |
  Gene-level counting of read pairs (fragments) over exons, grouped by gene_id.

  * -p --countReadPairs: count fragments, not reads (Subread >= 2.0.2 needs both).
  * -s: library strandedness, 2 = reverse (dUTP / TruSeq Stranded), which is what
    the UHR/HBR libraries are: the report infers it from the STAR counts and the
    QC gate fails if the two disagree.
  * Multi-mapping and ambiguous fragments are not counted (featureCounts default):
    they are reported in the summary instead.

  The first line of the table holds the command line with the thread count; the
  report writes a clean matrix (rnaseq.counts.tsv) without it, so the counts of
  two runs compare byte for byte.

hints:
  DockerRequirement:
    dockerPull: hg002-mini/rnaseq:1.0.0
  SoftwareRequirement:
    packages:
      subread: {version: ["2.1.1"], specs: ["https://bio.tools/subread"]}

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
      - entry: $(inputs.annotation)
        writable: false
      - $(inputs.bams)

inputs:
  bams: File[]
  annotation:
    type: File
    doc: "GTF with exon records and gene_id"
  strandedness:
    type: int
    default: 2
    doc: "0 unstranded, 1 stranded, 2 reversely stranded (featureCounts -s)"
  threads:
    type: int
    default: 4

baseCommand: [python3, measure.py]
arguments:
  - {prefix: --step, valueFrom: featurecounts}
  - {prefix: --out, valueFrom: featurecounts.metrics.json}
  - {prefix: --threads, valueFrom: $(inputs.threads)}
  - "--"
  - featureCounts
  - {prefix: -T, valueFrom: $(inputs.threads)}
  - -p
  - --countReadPairs
  - {prefix: -s, valueFrom: $(inputs.strandedness)}
  - {prefix: -t, valueFrom: exon}
  - {prefix: -g, valueFrom: gene_id}
  - {prefix: -a, valueFrom: $(inputs.annotation.basename)}
  - {prefix: -o, valueFrom: featureCounts.txt}
  - valueFrom: '${ return inputs.bams.map(function(f) { return f.basename; }); }'

outputs:
  counts:
    type: File
    outputBinding: {glob: featureCounts.txt}
  summary:
    type: File
    outputBinding: {glob: featureCounts.txt.summary}
  metrics:
    type: File
    outputBinding: {glob: featurecounts.metrics.json}
