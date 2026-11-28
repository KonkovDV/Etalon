cwlVersion: v1.2
class: Workflow
id: call_deepvariant
label: "DeepVariant on an existing BAM, benchmarked with hap.py"
doc: |
  Third caller on the alignments of mini-wgs.cwl, laid out like
  call-strelka2.cwl. vcf_clean drops run-specific header lines and indexes.

     bam ─► deepvariant ─► vcf_clean (VCF) ─► happy (scatter over truth sets)
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
  deepvariant:
    run: ../tools/deepvariant.cwl
    in:
      bam: bam
      reference: reference
      sample: sample
      threads: threads
    out: [vcf, gvcf, log, metrics]

  vcf_clean:
    run: ../tools/vcf-clean-header.cwl
    in:
      vcf: deepvariant/vcf
      out_name: {source: sample, valueFrom: "$(self).deepvariant.vcf.gz"}
      step_name: {default: deepvariant_vcf}
    out: [out, metrics]

  gvcf_clean:
    run: ../tools/vcf-clean-header.cwl
    in:
      vcf: deepvariant/gvcf
      out_name: {source: sample, valueFrom: "$(self).deepvariant.g.vcf.gz"}
      step_name: {default: deepvariant_gvcf}
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
  log:
    type: File
    outputSource: deepvariant/log
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
    outputSource: [deepvariant/metrics, vcf_clean/metrics, gvcf_clean/metrics, happy/metrics]
    linkMerge: merge_flattened
