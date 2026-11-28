#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
id: fastp
label: "fastp: adapter + poly-G trimming and read QC"
doc: |
  Minimal, variant-calling-friendly preprocessing of paired-end reads.

  * Adapters: trimmed from read-pair overlap, fastp's default for paired
    reads: where R1 and R2 overlap, the insert ends where they stop matching, so
    no adapter sequence has to be known. --detect_adapter_for_pe is NOT used:
    in fastp 1.4.0 it adds a single-threaded detection pass that took 37 of
    39 s on this dataset (2.1 s without it), see docs/DEBUGGING.md, D-05.
  * Poly-G: forced on (--trim_poly_g). On two-colour SBS chemistry (NovaSeq,
    NextSeq) "no signal" is called as G with high quality, so poly-G tails survive
    quality trimming and cause false mismatches at read ends.
  * No sliding-window quality trimming: the aligner soft-clips low-quality ends
    and the caller weights bases by quality; aggressive trimming loses data.

  The JSON report feeds the final report (Q30 rate, duplication, insert size).

$namespaces:
  s: https://schema.org/
  edam: http://edamontology.org/

hints:
  DockerRequirement:
    dockerPull: hg002-mini/tools:1.0.0
  SoftwareRequirement:
    packages:
      fastp:
        version: ["1.4.0"]
        specs: ["https://bio.tools/fastp"]

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
  reads_1:
    type: File
    format: edam:format_1930  # FASTQ
    doc: "R1 FASTQ (gzip/bgzip ok)"
  reads_2:
    type: File
    format: edam:format_1930
    doc: "R2 FASTQ (gzip/bgzip ok)"
  sample:
    type: string
  threads:
    type: int
    default: 4
  step_name:
    type: string
    default: fastp
    doc: "name of the step in the metrics; scattered runs pass fastp_<sample>"

baseCommand: [python3, measure.py]
arguments:
  - {prefix: --step, valueFrom: $(inputs.step_name)}
  - {prefix: --out, valueFrom: $(inputs.step_name).metrics.json}
  - {prefix: --threads, valueFrom: $(inputs.threads)}
  - "--"
  - fastp
  - {prefix: --in1, valueFrom: $(inputs.reads_1.path)}
  - {prefix: --in2, valueFrom: $(inputs.reads_2.path)}
  - {prefix: --out1, valueFrom: $(inputs.sample).trimmed_R1.fastq.gz}
  - {prefix: --out2, valueFrom: $(inputs.sample).trimmed_R2.fastq.gz}
  - --trim_poly_g
  - {prefix: --thread, valueFrom: $(inputs.threads)}
  - {prefix: --compression, valueFrom: "4"}
  - {prefix: --json, valueFrom: $(inputs.sample).fastp.json}
  - {prefix: --html, valueFrom: $(inputs.sample).fastp.html}
  - {prefix: --report_title, valueFrom: "$(inputs.sample) fastp report"}

outputs:
  trimmed_1:
    type: File
    format: edam:format_1930
    outputBinding: {glob: $(inputs.sample).trimmed_R1.fastq.gz}
  trimmed_2:
    type: File
    format: edam:format_1930
    outputBinding: {glob: $(inputs.sample).trimmed_R2.fastq.gz}
  report_json:
    type: File
    outputBinding: {glob: $(inputs.sample).fastp.json}
  report_html:
    type: File
    outputBinding: {glob: $(inputs.sample).fastp.html}
  metrics:
    type: File
    outputBinding: {glob: $(inputs.step_name).metrics.json}

s:author:
  - class: s:Person
    s:name: "hg002-mini-wgs contributors"
s:license: https://spdx.org/licenses/MIT
