#!/usr/bin/env cwl-runner
cwlVersion: v1.2
class: CommandLineTool
id: bwa_mem2_mem
label: "bwa-mem2 mem | samtools fixmate"
doc: |
  Aligns read pairs and adds mate information in one pipe (no SAM on disk).

  Reproducibility:
    -K 100000000  fixed number of input bases per batch. bwa-mem2 estimates the
                  insert-size distribution per batch; with a batch size tied to
                  the thread count (the default) the same input gives different
                  alignments at -t 4 and -t 16. With -K fixed it does not.
  Other flags:
    -Y            soft-clip supplementary alignments (keeps the full read
                  sequence in every record; standard for variant calling)
    -R            read group; SM becomes the sample name in the VCF

  The output is in name-grouped (bwa) order, which is what fixmate -m needs:
  it adds MC/ms tags used later by samtools markdup.

  Inputs are staged into the working directory and passed by basename. bwa-mem2
  writes its command line into the @PG header line; with absolute paths that line
  carried cwltool's random staging directories (/var/lib/cwl/stg<uuid>/...), so two
  identical runs gave BAMs with different headers (docs/DEBUGGING.md, D-08).

$namespaces:
  edam: http://edamontology.org/

hints:
  DockerRequirement:
    dockerPull: hg002-mini/tools:1.0.0
  SoftwareRequirement:
    packages:
      bwa-mem2: {version: ["2.3"], specs: ["https://bio.tools/bwa-mem2"]}
      samtools: {version: ["1.25"], specs: ["https://bio.tools/samtools"]}

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
      - $(inputs.reference)
      - $(inputs.reads_1)
      - $(inputs.reads_2)

inputs:
  reference:
    type: File
    secondaryFiles: [".0123", .amb, .ann, .bwt.2bit.64, .pac]
  reads_1: File
  reads_2: File
  sample: string
  library:
    type: string
    default: "lib1"
  platform:
    type: string
    default: "ILLUMINA"
  batch_bases:
    type: long
    default: 100000000
  simd:
    type: string
    default: ""
    doc: |
      Run one SIMD build of bwa-mem2 directly: sse41, sse42, avx, avx2 or
      avx512bw. Empty (default): the launcher picks the best build for this
      CPU, as in production. Forcing a lower build on a newer CPU shows whether
      nodes with different CPUs give the same alignments (docs/REPRODUCIBILITY.md).
      The build is started as `exec -a bwa-mem2`: the launcher keeps argv[0] =
      "bwa-mem2", so @PG CL in the BAM is then exactly what the launcher writes
      on a CPU where it would choose that build itself.
  threads:
    type: int
    default: 4

baseCommand: [python3, measure.py]
arguments:
  - {prefix: --step, valueFrom: bwa_mem2_mem}
  - {prefix: --out, valueFrom: bwa_mem2_mem.metrics.json}
  - {prefix: --threads, valueFrom: $(inputs.threads)}
  - "--"
  - bash
  - -euo
  - pipefail
  - -c
  - |
    $(inputs.simd ? "exec -a bwa-mem2 bwa-mem2." + inputs.simd : "bwa-mem2") mem \
        -t $(inputs.threads) \
        -K $(inputs.batch_bases) \
        -Y \
        -R '@RG\tID:$(inputs.sample).$(inputs.library)\tSM:$(inputs.sample)\tLB:$(inputs.library)\tPL:$(inputs.platform)' \
        '$(inputs.reference.basename)' '$(inputs.reads_1.basename)' '$(inputs.reads_2.basename)' \
      | samtools fixmate -m --no-PG -O bam,level=1 - '$(inputs.sample).fixmate.bam'

outputs:
  bam:
    type: File
    format: edam:format_2572  # BAM
    outputBinding: {glob: $(inputs.sample).fixmate.bam}
  metrics:
    type: File
    outputBinding: {glob: bwa_mem2_mem.metrics.json}
