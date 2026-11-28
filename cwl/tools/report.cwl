#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
id: report
label: "Run report: QC, benchmark with confidence intervals, per-step resources"
doc: |
  Aggregates everything the run produced into report.md and report.html (for people),
  report.json (for the QC gate, the results database and CI) and
  step_metrics.tsv (time / memory per step). See scripts/make_report.py.

hints:
  DockerRequirement:
    dockerPull: hg002-mini/tools:1.0.0

requirements:
  InlineJavascriptRequirement: {}
  ResourceRequirement:
    coresMin: 1
    ramMin: 512
  InitialWorkDirRequirement:
    listing:
      - entryname: make_report.py
        entry:
          $include: ../../scripts/make_report.py
      - entryname: render_html.py
        entry:
          $include: ../../scripts/render_html.py

inputs:
  sample: string
  step_metrics: File[]
  fastp_json: File
  markdup_json: File
  flagstat: File
  samtools_stats: File
  coverage: File
  bcftools_stats: File
  happy_names: string[]
  happy_summaries: File[]
  happy_extended: File[]
  happy_vcfs:
    type: File[]
    secondaryFiles: [.tbi]
  qc_thresholds: File?
  threads: int
  mpileup_profile: string

baseCommand: [python3, make_report.py]
arguments:
  - {prefix: --sample, valueFrom: $(inputs.sample)}
  - valueFrom: '${ return ["--metrics"].concat(inputs.step_metrics.map(function(f) { return f.path; })); }'
  - {prefix: --fastp, valueFrom: $(inputs.fastp_json.path)}
  - {prefix: --markdup, valueFrom: $(inputs.markdup_json.path)}
  - {prefix: --flagstat, valueFrom: $(inputs.flagstat.path)}
  - {prefix: --samtools-stats, valueFrom: $(inputs.samtools_stats.path)}
  - {prefix: --coverage, valueFrom: $(inputs.coverage.path)}
  - {prefix: --bcftools-stats, valueFrom: $(inputs.bcftools_stats.path)}
  - valueFrom: '${ return ["--happy-names"].concat(inputs.happy_names); }'
  - valueFrom: '${ return ["--happy-summary"].concat(inputs.happy_summaries.map(function(f) { return f.path; })); }'
  - valueFrom: '${ return ["--happy-extended"].concat(inputs.happy_extended.map(function(f) { return f.path; })); }'
  - valueFrom: '${ return ["--happy-vcf"].concat(inputs.happy_vcfs.map(function(f) { return f.path; })); }'
  - valueFrom: '${ return inputs.qc_thresholds ? ["--thresholds", inputs.qc_thresholds.path] : []; }'
  - {prefix: --threads, valueFrom: $(inputs.threads)}
  - {prefix: --mpileup-profile, valueFrom: $(inputs.mpileup_profile)}
  - {prefix: --out-md, valueFrom: $(inputs.sample).report.md}
  - {prefix: --out-html, valueFrom: $(inputs.sample).report.html}
  - {prefix: --out-json, valueFrom: $(inputs.sample).report.json}
  - {prefix: --out-tsv, valueFrom: $(inputs.sample).step_metrics.tsv}

outputs:
  report_md:
    type: File
    outputBinding: {glob: $(inputs.sample).report.md}
  report_html:
    type: File
    outputBinding: {glob: $(inputs.sample).report.html}
  report_json:
    type: File
    outputBinding: {glob: $(inputs.sample).report.json}
  step_metrics_tsv:
    type: File
    outputBinding: {glob: $(inputs.sample).step_metrics.tsv}
