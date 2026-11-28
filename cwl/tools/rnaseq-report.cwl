#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
id: rnaseq_report
label: "RNA-seq report: sample QC, ERCC linearity and fold-change accuracy, resources"
doc: |
  Turns the outputs of the RNA-seq workflow into rnaseq.report.md (for people),
  rnaseq.report.json (QC gate, evidence.json, CI), rnaseq.counts.tsv (gene x
  sample matrix without run-specific lines) and rnaseq.step_metrics.tsv. Runs in
  the RNA-seq image so that the tool versions of that image are reported. See
  scripts/rnaseq_report.py.

hints:
  DockerRequirement:
    dockerPull: hg002-mini/rnaseq:1.0.0

requirements:
  InlineJavascriptRequirement: {}
  ResourceRequirement:
    coresMin: 1
    ramMin: 512
  InitialWorkDirRequirement:
    listing:
      - entryname: rnaseq_report.py
        entry:
          $include: ../../scripts/rnaseq_report.py

inputs:
  samples: string[]
  groups: string[]
  ercc_mixes: string[]
  counts: File
  counts_summary: File
  star_logs: File[]
  star_gene_counts: File[]
  fastp_json: File[]
  ercc_table: File
  annotation: File
  strandedness: int
  step_metrics: File[]
  qc_thresholds: File?
  threads: int

baseCommand: [python3, rnaseq_report.py]
arguments:
  - valueFrom: '${ return ["--samples"].concat(inputs.samples); }'
  - valueFrom: '${ return ["--groups"].concat(inputs.groups); }'
  - valueFrom: '${ return ["--mixes"].concat(inputs.ercc_mixes); }'
  - {prefix: --counts, valueFrom: $(inputs.counts.path)}
  - {prefix: --counts-summary, valueFrom: $(inputs.counts_summary.path)}
  - valueFrom: '${ return ["--star-logs"].concat(inputs.star_logs.map(function(f) { return f.path; })); }'
  - valueFrom: '${ return ["--star-gene-counts"].concat(inputs.star_gene_counts.map(function(f) { return f.path; })); }'
  - valueFrom: '${ return ["--fastp-json"].concat(inputs.fastp_json.map(function(f) { return f.path; })); }'
  - {prefix: --ercc, valueFrom: $(inputs.ercc_table.path)}
  - {prefix: --annotation, valueFrom: $(inputs.annotation.path)}
  - {prefix: --strandedness, valueFrom: $(inputs.strandedness)}
  - valueFrom: '${ return ["--step-metrics"].concat(inputs.step_metrics.map(function(f) { return f.path; })); }'
  - {prefix: --versions, valueFrom: /opt/rnaseq/TOOL_VERSIONS.tsv}
  - valueFrom: '${ return inputs.qc_thresholds ? ["--qc-thresholds", inputs.qc_thresholds.path] : []; }'
  - {prefix: --threads, valueFrom: $(inputs.threads)}
  - {prefix: --out-prefix, valueFrom: rnaseq}

outputs:
  report_md:
    type: File
    outputBinding: {glob: rnaseq.report.md}
  report_json:
    type: File
    outputBinding: {glob: rnaseq.report.json}
  counts_tsv:
    type: File
    outputBinding: {glob: rnaseq.counts.tsv}
  step_metrics_tsv:
    type: File
    outputBinding: {glob: rnaseq.step_metrics.tsv}
