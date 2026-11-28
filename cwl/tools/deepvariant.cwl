#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
id: deepvariant
label: "DeepVariant 1.10 (WGS model): small variants and gVCF for one sample"
doc: |
  DeepVariant (Poplin et al., Nat Biotechnol 2018) turns pileups around
  candidate sites into images and genotypes them with a convolutional network.
  run_deepvariant chains make_examples (sharded, --num_shards = threads),
  call_variants (TensorFlow on CPU) and postprocess_variants.

  The WGS model was trained on GIAB samples including HG002, but chr20-22 are
  always held out of training (DeepVariant docs), so this region is an honest
  test of the model. The reference and BAM are staged and passed by basename.
  The HTML stats report is switched off; the full log is an output.
  The image runs Python 3.10.

hints:
  DockerRequirement:
    dockerPull: google/deepvariant@sha256:962e5a83b1d76aae6990625d47102785f791603f2138aa1fa9aa4fb6a2eecbe6
  SoftwareRequirement:
    packages:
      deepvariant: {version: ["1.10.0"], specs: ["https://bio.tools/deepvariant"]}

requirements:
  InlineJavascriptRequirement: {}
  ResourceRequirement:
    coresMin: $(inputs.threads)
    ramMin: 8192
  InitialWorkDirRequirement:
    listing:
      - entryname: measure.py
        entry:
          $include: ../../bin/measure.py
      - $(inputs.reference)
      - $(inputs.bam)

inputs:
  bam:
    type: File
    secondaryFiles: [.bai]
  reference:
    type: File
    secondaryFiles: [.fai]
  sample: string
  model_type:
    type: string
    default: WGS
  threads:
    type: int
    default: 4

baseCommand: [python3, measure.py]
arguments:
  - {prefix: --step, valueFrom: deepvariant}
  - {prefix: --out, valueFrom: deepvariant.metrics.json}
  - {prefix: --threads, valueFrom: $(inputs.threads)}
  - "--"
  - bash
  - -euo
  - pipefail
  - -c
  - |
    mkdir -p dv_tmp
    /opt/deepvariant/bin/run_deepvariant \
        --model_type=$(inputs.model_type) \
        --ref='$(inputs.reference.basename)' \
        --reads='$(inputs.bam.basename)' \
        --sample_name='$(inputs.sample)' \
        --output_vcf='$(inputs.sample).deepvariant.raw.vcf.gz' \
        --output_gvcf='$(inputs.sample).deepvariant.raw.g.vcf.gz' \
        --num_shards=$(inputs.threads) \
        --vcf_stats_report=false \
        --intermediate_results_dir=dv_tmp > deepvariant.log 2>&1
    rm -rf dv_tmp

outputs:
  vcf:
    type: File
    outputBinding: {glob: $(inputs.sample).deepvariant.raw.vcf.gz}
  gvcf:
    type: File
    outputBinding: {glob: $(inputs.sample).deepvariant.raw.g.vcf.gz}
  log:
    type: File
    outputBinding: {glob: deepvariant.log}
  metrics:
    type: File
    outputBinding: {glob: deepvariant.metrics.json}
