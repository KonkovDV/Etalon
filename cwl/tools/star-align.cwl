#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
id: star_align
label: "STAR: spliced alignment of paired reads, coordinate-sorted BAM, per-gene counts"
doc: |
  Spliced alignment with the ENCODE long RNA-seq options of the STAR manual:
  --outFilterType BySJout, at most 20 loci per read, mismatches <= 4 % of the
  mapped length, introns 20 b - 1 Mb, 8 b overhang for new junctions and 1 b for
  annotated ones.

  * --outSAMtype BAM SortedByCoordinate: STAR sorts by (position, read number in
    the input), so equal positions are ordered by the FASTQ, not by the thread
    that mapped the read, and the record order does not depend on --runThreadN
    (docs/REPRODUCIBILITY.md). PairedKeepInputOrder would give the same, but STAR
    accepts it only for SAM output.
  * --quantMode GeneCounts: a second, independent counter. Its three columns
    (unstranded, read 1 on the transcript strand, read 2 on it) tell the library
    strandedness; the report compares them with featureCounts.
  * NH HI AS nM NM MD: NH lets featureCounts skip multi-mapping reads; MD and NM
    keep mismatch information for downstream tools.
  * No --outTmpDir: a staging path in the command line would end up in the BAM
    header (@PG, @CO). STAR uses <prefix>_STARtmp in the working directory.

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
      - entry: $(inputs.index)
        writable: false
      - entry: $(inputs.reads_1)
        writable: false
      - entry: $(inputs.reads_2)
        writable: false

inputs:
  index:
    type: Directory
    doc: "output of star-index.cwl"
  reads_1:
    type: File
    format: edam:format_1930  # FASTQ
  reads_2:
    type: File
    format: edam:format_1930
  sample: string
  threads:
    type: int
    default: 4

baseCommand: [python3, measure.py]
arguments:
  - {prefix: --step, valueFrom: "star_align_$(inputs.sample)"}
  - {prefix: --out, valueFrom: "star_align_$(inputs.sample).metrics.json"}
  - {prefix: --threads, valueFrom: $(inputs.threads)}
  - "--"
  - STAR
  - {prefix: --runThreadN, valueFrom: $(inputs.threads)}
  - {prefix: --genomeDir, valueFrom: $(inputs.index.basename)}
  - --readFilesIn
  - $(inputs.reads_1.basename)
  - $(inputs.reads_2.basename)
  - {prefix: --readFilesCommand, valueFrom: zcat}
  - {prefix: --outFileNamePrefix, valueFrom: $(inputs.sample).}
  - --outSAMtype
  - BAM
  - SortedByCoordinate
  - --outSAMattributes
  - NH
  - HI
  - AS
  - nM
  - NM
  - MD
  - --outSAMattrRGline
  - ID:$(inputs.sample)
  - SM:$(inputs.sample)
  - PL:ILLUMINA
  - {prefix: --outFilterType, valueFrom: BySJout}
  - {prefix: --outFilterMultimapNmax, valueFrom: "20"}
  - {prefix: --outFilterMismatchNmax, valueFrom: "999"}
  - {prefix: --outFilterMismatchNoverReadLmax, valueFrom: "0.04"}
  - {prefix: --alignIntronMin, valueFrom: "20"}
  - {prefix: --alignIntronMax, valueFrom: "1000000"}
  - {prefix: --alignMatesGapMax, valueFrom: "1000000"}
  - {prefix: --alignSJoverhangMin, valueFrom: "8"}
  - {prefix: --alignSJDBoverhangMin, valueFrom: "1"}
  - {prefix: --sjdbScore, valueFrom: "1"}
  - {prefix: --quantMode, valueFrom: GeneCounts}

outputs:
  bam:
    type: File
    format: edam:format_2572  # BAM
    outputBinding: {glob: $(inputs.sample).Aligned.sortedByCoord.out.bam}
  log_final:
    type: File
    outputBinding: {glob: $(inputs.sample).Log.final.out}
  log:
    type: File
    outputBinding: {glob: $(inputs.sample).Log.out}
  splice_junctions:
    type: File
    outputBinding: {glob: $(inputs.sample).SJ.out.tab}
  gene_counts:
    type: File
    outputBinding: {glob: $(inputs.sample).ReadsPerGene.out.tab}
  metrics:
    type: File
    outputBinding: {glob: "star_align_$(inputs.sample).metrics.json"}
