cwlVersion: v1.2
class: Workflow
id: call_strelka2
label: "Strelka2 on an existing BAM, benchmarked with hap.py"
doc: |
  Second caller on the alignments of mini-wgs.cwl, so the callers differ in
  one thing only. scripts/compare_callers.py compares the hap.py outputs of
  this workflow with those of the main run.

     bam ─► strelka2_germline ─► vcf_clean (VCF) ─► happy (scatter over truth sets)
                              └► gvcf_clean (gVCF)

requirements:
  ScatterFeatureRequirement: {}
  MultipleInputFeatureRequirement: {}
  StepInputExpressionRequirement: {}
  InlineJavascriptRequirement: {}

inputs:
  sample:
    type: string
    default: HG002
  bam:
    type: File
    secondaryFiles: [.bai]
  reference:
    type: File
    secondaryFiles: [.fai]
  truth_names: string[]
  truth_vcfs:
    type: File[]
    secondaryFiles: [.tbi]
  truth_beds: File[]
  stratification:
    type: Directory?
  threads:
    type: int
    default: 4

steps:
  strelka2_germline:
    run: ../tools/strelka2-germline.cwl
    in:
      bam: bam
      reference: reference
      sample: sample
      threads: threads
    out: [vcf, gvcf, run_stats, configure_log, metrics]

  vcf_clean:
    run: ../tools/vcf-clean-header.cwl
    in:
      vcf: strelka2_germline/vcf
      out_name: {source: sample, valueFrom: "$(self).strelka2.vcf.gz"}
      step_name: {default: strelka2_vcf}
    out: [out, metrics]

  gvcf_clean:
    run: ../tools/vcf-clean-header.cwl
    in:
      vcf: strelka2_germline/gvcf
      out_name: {source: sample, valueFrom: "$(self).strelka2.g.vcf.gz"}
      step_name: {default: strelka2_gvcf}
    out: [out, metrics]

  happy:
    run: ../tools/happy.cwl
    scatter: [truth_name, truth_vcf, truth_bed]
    scatterMethod: dotproduct
    in:
      truth_name: truth_names
      truth_vcf: truth_vcfs
      truth_bed: truth_beds
      query_vcf: vcf_clean/out
      reference: reference
      stratification: stratification
      threads: threads
    out: [summary, extended, annotated_vcf, metrics_json, runinfo, roc_all, metrics]

outputs:
  vcf:
    type: File
    secondaryFiles: [.tbi]
    outputSource: vcf_clean/out
  gvcf:
    type: File
    secondaryFiles: [.tbi]
    outputSource: gvcf_clean/out
  run_stats:
    type: File
    outputSource: strelka2_germline/run_stats
  configure_log:
    type: File
    outputSource: strelka2_germline/configure_log
  happy_summary:
    type: File[]
    outputSource: happy/summary
  happy_extended:
    type: File[]
    outputSource: happy/extended
  happy_vcf:
    type: File[]
    secondaryFiles: [.tbi]
    outputSource: happy/annotated_vcf
  step_metrics:
    type: File[]
    outputSource: [strelka2_germline/metrics, vcf_clean/metrics, gvcf_clean/metrics, happy/metrics]
    linkMerge: merge_flattened
