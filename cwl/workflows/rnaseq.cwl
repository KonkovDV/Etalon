#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: Workflow
id: rnaseq
label: "RNA-seq: FASTQ -> fastp -> STAR -> featureCounts, checked against ERCC spike-ins"
doc: |
  Bulk RNA-seq for a set of samples with ERCC spike-ins. Every step writes
  <step>.metrics.json through bin/measure.py, as in the WGS workflow; the report
  step turns STAR logs, both gene counters and the ERCC truth table into
  rnaseq.report.md / .json and a clean count matrix.

     reads_1[i], reads_2[i] ─► fastp ─► star_align ─┬─► bam_finalize ─► featurecounts (all samples) ─┐
     reference, annotation ─► star_index ─┘          └─► ReadsPerGene (STAR) ──────────────────────────┴─► report
                                                                                          ercc_table ──┘

$namespaces:
  s: https://schema.org/
  edam: http://edamontology.org/

requirements:
  ScatterFeatureRequirement: {}
  MultipleInputFeatureRequirement: {}
  StepInputExpressionRequirement: {}
  InlineJavascriptRequirement: {}

inputs:
  samples:
    type: string[]
    doc: "sample names, same order as every per-sample array"
  groups:
    type: string[]
    doc: "condition of each sample (UHR, HBR)"
  ercc_mixes:
    type: string[]
    doc: "ERCC mix added to each sample: Mix1 or Mix2"
  reads_1: File[]
  reads_2: File[]
  reference:
    type: File
    format: edam:format_1929
  annotation: File
  ercc_table:
    type: File
    doc: "ERCC concentration table (Thermo Fisher cms_095046)"
  strandedness:
    type: int
    default: 2
  sjdb_overhang:
    type: int
    default: 99
  sa_index_nbases:
    type: int
    default: 11
  threads:
    type: int
    default: 4
  qc_thresholds:
    type: File?

steps:
  star_index:
    run: ../tools/star-index.cwl
    in:
      reference: reference
      annotation: annotation
      sjdb_overhang: sjdb_overhang
      sa_index_nbases: sa_index_nbases
      threads: threads
    out: [index, metrics]

  fastp:
    run: ../tools/fastp.cwl
    scatter: [reads_1, reads_2, sample]
    scatterMethod: dotproduct
    in:
      reads_1: reads_1
      reads_2: reads_2
      sample: samples
      threads: threads
      step_name:
        valueFrom: "fastp_$(inputs.sample)"
    out: [trimmed_1, trimmed_2, report_json, report_html, metrics]

  star_align:
    run: ../tools/star-align.cwl
    scatter: [reads_1, reads_2, sample]
    scatterMethod: dotproduct
    in:
      index: star_index/index
      reads_1: fastp/trimmed_1
      reads_2: fastp/trimmed_2
      sample: samples
      threads: threads
    out: [bam, log_final, log, splice_junctions, gene_counts, metrics]

  bam_finalize:
    run: ../tools/bam-finalize.cwl
    scatter: [bam, sample]
    scatterMethod: dotproduct
    in:
      bam: star_align/bam
      sample: samples
      threads: threads
    out: [bam_indexed, metrics]

  featurecounts:
    run: ../tools/featurecounts.cwl
    in:
      bams: bam_finalize/bam_indexed
      annotation: annotation
      strandedness: strandedness
      threads: threads
    out: [counts, summary, metrics]

  report:
    run: ../tools/rnaseq-report.cwl
    in:
      samples: samples
      groups: groups
      ercc_mixes: ercc_mixes
      counts: featurecounts/counts
      counts_summary: featurecounts/summary
      star_logs: star_align/log_final
      star_gene_counts: star_align/gene_counts
      fastp_json: fastp/report_json
      ercc_table: ercc_table
      annotation: annotation
      strandedness: strandedness
      step_metrics:
        source: [star_index/metrics, fastp/metrics, star_align/metrics, bam_finalize/metrics, featurecounts/metrics]
        linkMerge: merge_flattened
      qc_thresholds: qc_thresholds
      threads: threads
    out: [report_md, report_json, counts_tsv, step_metrics_tsv]

outputs:
  bams:
    type: File[]
    secondaryFiles: [.bai]
    outputSource: bam_finalize/bam_indexed
  star_logs:
    type: File[]
    outputSource: star_align/log_final
  splice_junctions:
    type: File[]
    outputSource: star_align/splice_junctions
  star_gene_counts:
    type: File[]
    outputSource: star_align/gene_counts
  fastp_json:
    type: File[]
    outputSource: fastp/report_json
  fastp_html:
    type: File[]
    outputSource: fastp/report_html
  featurecounts:
    type: File
    outputSource: featurecounts/counts
  featurecounts_summary:
    type: File
    outputSource: featurecounts/summary
  step_metrics:
    type: File[]
    outputSource: [star_index/metrics, fastp/metrics, star_align/metrics, bam_finalize/metrics, featurecounts/metrics]
    linkMerge: merge_flattened
  report_md:
    type: File
    outputSource: report/report_md
  report_json:
    type: File
    outputSource: report/report_json
  counts_tsv:
    type: File
    outputSource: report/counts_tsv
  step_metrics_tsv:
    type: File
    outputSource: report/step_metrics_tsv

s:license: https://spdx.org/licenses/MIT
s:codeRepository: https://github.com/KonkovDV/Etalon
