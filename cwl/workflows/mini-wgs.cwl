#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: Workflow
id: mini_wgs
label: "HG002 mini-WGS: FASTQ -> fastp -> bwa-mem2 -> samtools -> bcftools -> hap.py"
doc: |
  Germline short-variant pipeline for one sample, benchmarked against GIAB
  truth sets. Every step writes <step>.metrics.json (wall time, CPU, peak RSS)
  through bin/measure.py; the report step turns them, the QC files and the
  hap.py results into report.md / report.json.

     reads_1, reads_2 ─► fastp ─► bwa_mem2_mem ─► samtools_sort ─► samtools_markdup ─┬─► samtools_qc
     reference ─► bwa_mem2_index ─┘                                                    └─► bcftools_call
                                                                                          ─► bcftools_filter ─┬─► bcftools_stats
                                    truth_names/vcfs/beds (scatter) ─► happy ◄────────────────────────────────┘
                                                                         └──────► report ◄── all metrics + QC

$namespaces:
  s: https://schema.org/
  edam: http://edamontology.org/

requirements:
  ScatterFeatureRequirement: {}
  MultipleInputFeatureRequirement: {}
  StepInputExpressionRequirement: {}
  InlineJavascriptRequirement: {}

inputs:
  sample:
    type: string
    default: HG002
  reads_1:
    type: File
    format: edam:format_1930
  reads_2:
    type: File
    format: edam:format_1930
  reference:
    type: File
    format: edam:format_1929
    doc: "FASTA without indexes; indexes are built by the workflow"
  truth_names:
    type: string[]
    doc: "labels of the truth sets, same order as truth_vcfs/truth_beds"
  truth_vcfs:
    type: File[]
    secondaryFiles: [.tbi]
  truth_beds: File[]
  stratification:
    type: Directory?
  threads:
    type: int
    default: 4
  bwa_simd:
    type: string
    default: ""
    doc: "SIMD build of bwa-mem2 to force (sse41, avx2, ...); empty = chosen by the CPU"
  mpileup_profile:
    type: string
    default: "illumina"
  min_qual:
    type: float
    default: 20
  min_depth:
    type: int
    default: 5
  max_depth:
    type: int
    default: 120
  qc_thresholds:
    type: File?
    doc: "JSON with minimal recall/precision per truth set and variant type"

steps:
  fastp:
    run: ../tools/fastp.cwl
    in:
      reads_1: reads_1
      reads_2: reads_2
      sample: sample
      threads: threads
    out: [trimmed_1, trimmed_2, report_json, report_html, metrics]

  bwa_mem2_index:
    run: ../tools/bwa-mem2-index.cwl
    in:
      reference: reference
    out: [indexed_reference, metrics]

  bwa_mem2_mem:
    run: ../tools/bwa-mem2-mem.cwl
    in:
      reference: bwa_mem2_index/indexed_reference
      reads_1: fastp/trimmed_1
      reads_2: fastp/trimmed_2
      sample: sample
      simd: bwa_simd
      threads: threads
    out: [bam, metrics]

  samtools_sort:
    run: ../tools/samtools-sort.cwl
    in:
      bam: bwa_mem2_mem/bam
      sample: sample
      threads: threads
    out: [sorted_bam, metrics]

  samtools_markdup:
    run: ../tools/samtools-markdup.cwl
    in:
      sorted_bam: samtools_sort/sorted_bam
      sample: sample
      threads: threads
    out: [bam, markdup_json, metrics]

  samtools_qc:
    run: ../tools/samtools-qc.cwl
    in:
      bam: samtools_markdup/bam
      reference: bwa_mem2_index/indexed_reference
      sample: sample
      threads: threads
    out: [flagstat, stats, coverage, metrics]

  bcftools_call:
    run: ../tools/bcftools-call.cwl
    in:
      bam: samtools_markdup/bam
      reference: bwa_mem2_index/indexed_reference
      sample: sample
      mpileup_profile: mpileup_profile
    out: [calls, metrics]

  bcftools_filter:
    run: ../tools/bcftools-filter.cwl
    in:
      calls: bcftools_call/calls
      reference: bwa_mem2_index/indexed_reference
      sample: sample
      min_qual: min_qual
      min_depth: min_depth
      max_depth: max_depth
    out: [vcf, metrics]

  bcftools_stats:
    run: ../tools/bcftools-stats.cwl
    in:
      vcf: bcftools_filter/vcf
      reference: bwa_mem2_index/indexed_reference
      sample: sample
    out: [stats, metrics]

  happy:
    run: ../tools/happy.cwl
    scatter: [truth_name, truth_vcf, truth_bed]
    scatterMethod: dotproduct
    in:
      truth_name: truth_names
      truth_vcf: truth_vcfs
      truth_bed: truth_beds
      query_vcf: bcftools_filter/vcf
      reference: bwa_mem2_index/indexed_reference
      stratification: stratification
      threads: threads
    out: [summary, extended, annotated_vcf, metrics_json, runinfo, roc_all, metrics]

  report:
    run: ../tools/report.cwl
    in:
      sample: sample
      step_metrics:
        source:
          - fastp/metrics
          - bwa_mem2_index/metrics
          - bwa_mem2_mem/metrics
          - samtools_sort/metrics
          - samtools_markdup/metrics
          - samtools_qc/metrics
          - bcftools_call/metrics
          - bcftools_filter/metrics
          - bcftools_stats/metrics
          - happy/metrics
        linkMerge: merge_flattened
      fastp_json: fastp/report_json
      markdup_json: samtools_markdup/markdup_json
      flagstat: samtools_qc/flagstat
      samtools_stats: samtools_qc/stats
      coverage: samtools_qc/coverage
      bcftools_stats: bcftools_stats/stats
      happy_names: truth_names
      happy_summaries: happy/summary
      happy_extended: happy/extended
      happy_vcfs: happy/annotated_vcf
      qc_thresholds: qc_thresholds
      threads: threads
      mpileup_profile: mpileup_profile
    out: [report_md, report_html, report_json, step_metrics_tsv]

outputs:
  bam:
    type: File
    secondaryFiles: [.bai]
    outputSource: samtools_markdup/bam
  vcf:
    type: File
    secondaryFiles: [.tbi]
    outputSource: bcftools_filter/vcf
  fastp_html:
    type: File
    outputSource: fastp/report_html
  fastp_json:
    type: File
    outputSource: fastp/report_json
  markdup_json:
    type: File
    outputSource: samtools_markdup/markdup_json
  flagstat:
    type: File
    outputSource: samtools_qc/flagstat
  samtools_stats:
    type: File
    outputSource: samtools_qc/stats
  coverage:
    type: File
    outputSource: samtools_qc/coverage
  bcftools_stats:
    type: File
    outputSource: bcftools_stats/stats
  happy_summary:
    type: File[]
    outputSource: happy/summary
  happy_extended:
    type: File[]
    outputSource: happy/extended
  happy_vcf:
    type: File[]
    outputSource: happy/annotated_vcf
  happy_runinfo:
    type: File[]
    outputSource: happy/runinfo
  happy_roc:
    type: File[]
    outputSource: happy/roc_all
  step_metrics:
    type: File[]
    outputSource:
      - fastp/metrics
      - bwa_mem2_index/metrics
      - bwa_mem2_mem/metrics
      - samtools_sort/metrics
      - samtools_markdup/metrics
      - samtools_qc/metrics
      - bcftools_call/metrics
      - bcftools_filter/metrics
      - bcftools_stats/metrics
      - happy/metrics
    linkMerge: merge_flattened
  report_md:
    type: File
    outputSource: report/report_md
  report_html:
    type: File
    outputSource: report/report_html
  report_json:
    type: File
    outputSource: report/report_json
  step_metrics_tsv:
    type: File
    outputSource: report/step_metrics_tsv

s:license: https://spdx.org/licenses/MIT
s:codeRepository: https://github.com/your-account/hg002-mini-wgs
