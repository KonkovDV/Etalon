#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
id: star_index
label: "STAR genomeGenerate: genome index with annotated splice junctions"
doc: |
  Builds the STAR index once per reference and annotation.

  * --sjdbGTFfile inserts the annotated splice junctions into the index; mapping
    then finds known junctions with short overhangs (--alignSJDBoverhangMin 1).
  * --sjdbOverhang = read length - 1 (99 for 2x100 reads), the value the STAR
    manual recommends.
  * --genomeSAindexNbases = min(14, log2(genome length) / 2 - 1): 11 for chr22 +
    ERCC92 (50.9 Mb). The default 14 is for a whole human genome; on a small
    genome it wastes memory and STAR may crash in mapping (STAR manual, 2.2.5).

  Inputs are staged into the working directory and passed by name, so no
  cwltool staging path lands in the index parameters. In genomeGenerate mode
  STAR writes its Log.out into the index directory itself.

$namespaces:
  edam: http://edamontology.org/

hints:
  DockerRequirement:
    dockerPull: hg002-mini/rnaseq:1.0.0
  SoftwareRequirement:
    packages:
      star: {version: ["2.7.11b"], specs: ["https://bio.tools/star"]}

requirements:
  InlineJavascriptRequirement: {}
  ResourceRequirement:
    coresMin: $(inputs.threads)
    ramMin: 4096
  InitialWorkDirRequirement:
    listing:
      - entryname: measure.py
        entry:
          $include: ../../bin/measure.py
      - entry: $(inputs.reference)
        writable: false
      - entry: $(inputs.annotation)
        writable: false

inputs:
  reference:
    type: File
    format: edam:format_1929  # FASTA
  annotation:
    type: File
    doc: "GTF; exons grouped by transcript_id"
  sjdb_overhang:
    type: int
    default: 99
  sa_index_nbases:
    type: int
    default: 11
  threads:
    type: int
    default: 4

baseCommand: [python3, measure.py]
arguments:
  - {prefix: --step, valueFrom: star_index}
  - {prefix: --out, valueFrom: star_index.metrics.json}
  - {prefix: --threads, valueFrom: $(inputs.threads)}
  - "--"
  - STAR
  - {prefix: --runMode, valueFrom: genomeGenerate}
  - {prefix: --runThreadN, valueFrom: $(inputs.threads)}
  - {prefix: --genomeDir, valueFrom: star_index}
  - {prefix: --genomeFastaFiles, valueFrom: $(inputs.reference.basename)}
  - {prefix: --sjdbGTFfile, valueFrom: $(inputs.annotation.basename)}
  - {prefix: --sjdbOverhang, valueFrom: $(inputs.sjdb_overhang)}
  - {prefix: --genomeSAindexNbases, valueFrom: $(inputs.sa_index_nbases)}

outputs:
  index:
    type: Directory
    outputBinding: {glob: star_index}
  metrics:
    type: File
    outputBinding: {glob: star_index.metrics.json}
