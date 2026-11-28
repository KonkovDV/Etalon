# Etalon: WGS and RNA-seq pipelines checked against reference samples

Project site with the reports and docs: https://konkovdv.github.io/Etalon/ · [Русская версия](README.md) is the main README, with every number linked to its evidence.

An open project on checking sequencing pipelines against reference samples. WGS is compared with GIAB HG002, RNA-seq with ERCC spike-ins of known concentration. Accuracy is reported with 95 % intervals and per genome stratum, runs are byte-identical, and every number in the texts is checked against the data in CI.

The WGS part is a germline short-variant pipeline for one human sample, from raw reads to calls and their comparison with the GIAB truth sets. It is written in CWL v1.2; every tool runs in a Docker image pinned by digest, with htslib, samtools and bcftools compiled from source together with their test suites. It runs under Slurm (single node, Toil with one Slurm job per step, or a job array for a cohort) and is checked in GitLab CI.

Data: a 2 Mb region of chr20 (genes *SNAP25*, *MKKS*, *JAG1*) sequenced on NovaSeq 6000, PCR-free, 2×151, ~35x. One run takes about a minute on a laptop.

## Results (reference run, PASS calls)

| Truth set | SNV F1 [95 % CI] | Indel F1 [95 % CI] |
|---|---|---|
| GIAB v5.0q (assembly-based, current) | <!--ev:snp_v5_f1-->0.9868<!--/ev--> [<!--ev:snp_v5_f1_ci-->0.983–0.990<!--/ev-->] | <!--ev:indel_v5_f1-->0.9081<!--/ev--> [<!--ev:indel_v5_f1_ci-->0.890–0.923<!--/ev-->] |
| GIAB v4.2.1 (legacy) | <!--ev:snp_v421_f1-->0.9977<!--/ev--> [<!--ev:snp_v421_f1_ci-->0.996–0.999<!--/ev-->] | <!--ev:indel_v421_f1-->0.9804<!--/ev--> [<!--ev:indel_v421_f1_ci-->0.969–0.988<!--/ev-->] |

- The same calls score lower against v5.0q because it covers difficult regions that v4.2.1 excludes. Errors concentrate in tandem repeats (SNV F1 <!--ev:snp_v5_tr_f1-->0.800<!--/ev-->) and homopolymers; outside difficult regions SNV F1 is <!--ev:snp_v5_easy_f1-->0.999<!--/ev-->.
- bcftools' consensus-based indel model (`-X illumina`, bcftools ≥ 1.20) raises indel F1 on v5.0q from <!--ev:indel_v5_f1_legacy-->0.8399<!--/ev--> to <!--ev:indel_v5_f1-->0.9081<!--/ev-->; the 95 % intervals do not overlap.
- The VCF is byte-identical in all <!--ev:repro_comparisons-->10<!--/ev--> comparisons: 4 vs 2 threads, a repeated run, cwltool vs Toil on Slurm, an image rebuilt from scratch, a second machine behind a TLS-inspecting proxy, and all five SIMD builds of bwa-mem2 (SSE4.1 to AVX-512BW).

## Callers and the acceptance metric

- On the same BAM, Strelka2 (the production caller of large population projects) is more accurate than bcftools: on v5.0q SNV F1 <!--ev:strelka2_snp_v5_f1-->0.9955<!--/ev--> vs <!--ev:bcftools_snp_v5_f1-->0.9868<!--/ev-->, indel F1 <!--ev:strelka2_indel_v5_f1-->0.9383<!--/ev--> vs <!--ev:bcftools_indel_v5_f1-->0.9081<!--/ev-->, mostly through fewer false calls in difficult regions. DeepVariant 1.10 matches Strelka2 on F1, finds more true indels (paired McNemar p = <!--ev:mcnemar_indel_v5_strelka2_dv_p-->0.004<!--/ev-->) and uses <!--ev:dv_vs_strelka2_cpu_x-->8.6<!--/ev-->× the CPU. VCF and gVCF of both are byte-identical at 4 and 2 threads.
- The genotype-concordance metric of patent RU 2846268 (F > 99.9 % among calls matching the truth by CHR/POS/REF/ALT) is computed next to GA4GH metrics on the same calls: <!--ev:patent_pass_v421-->1<!--/ev--> of 3 callers passes the threshold on v4.2.1 and <!--ev:patent_pass_v5-->0<!--/ev--> on v5.0q, and missed or extra calls never enter F. Details (in Russian): `docs/PRODUCTION.md`, `docs/METRICS.md`.

## Accuracy against depth

The read pairs are thinned to 5–35x (`samtools view -s SEED.FRACTION`, seven depths, three seeds at ~10x and ~21x), and the pipeline and the three callers run again at every depth (`make depth`). The patent metric F behaves unlike F1: at <!--ev:depth_f145_x-->5.5<!--/ev-->x all three callers pass the 99.9 % threshold with F = 100 %, because the sum(AD) > 10 filter leaves only <!--ev:depth_f145_bcftools_share_v421-->1.8<!--/ev-->–<!--ev:depth_f145_dv_share_v421-->3.5<!--/ev--> % of the truth set in its denominator, while SNV F1 is <!--ev:depth_f145_bcftools_snp_f1-->0.695<!--/ev-->–<!--ev:depth_f145_dv_snp_f1-->0.874<!--/ev-->. Seeds alone move F of bcftools at ~10x by <!--ev:depth_rep_f290_bcftools_f_v421_span-->0.28<!--/ev--> percentage points. Next to F one should report the share of the truth set in its denominator, or recall.

## Frequency database

- The same variants are written differently by different callers: <!--ev:repr_share_min-->17<!--/ev-->–<!--ev:repr_share_max-->53<!--/ev--> % of the key-level (CHROM, POS, REF, ALT) differences between two callers on one BAM are representation, not different variants. Splitting multi-allelic records removes <!--ev:repr_split_share_min-->17<!--/ev-->–<!--ev:repr_split_share_max-->30<!--/ev--> %; the rest is the same haplotype decomposed into other records, which normalisation cannot fix. Each of the <!--ev:repr_loci_total-->16<!--/ev--> such cases was checked without hap.py, by rebuilding the haplotypes from the reference over all phasings.
- AN should count only samples whose genotype is known (gVCF, GQ ≥ <!--ev:callable_gq_min-->20<!--/ev-->). In a cohort of HG002 copies at different depths, where the right AF is known in advance, AN = 2N gives heterozygous AF <!--ev:cohort_all_het_naive-->0.475<!--/ev--> instead of 0.5, known genotypes only give <!--ev:cohort_all_het_honest-->0.496<!--/ev-->. `scripts/results_db.py` has both views.

## RNA-seq

A second workflow (`cwl/workflows/rnaseq.cwl`) runs fastp → STAR 2.7.11b → featureCounts on UHR and HBR reference RNA, three replicates each, with ERCC spike-in mixes 1 and 2. The 92 ERCC transcripts have known concentrations, so the RNA-seq side is checked against a truth set too:

- linearity: fragments per kilobase against ERCC concentration give slopes of <!--ev:rnaseq_slope_min-->0.94<!--/ev-->–<!--ev:rnaseq_slope_max-->0.99<!--/ev--> (1 in theory; the 95 % interval covers 1 in <!--ev:rnaseq_slope_ci_cover_1-->6<!--/ev--> samples of 6), R² ≥ <!--ev:rnaseq_r2_min-->0.966<!--/ev-->;
- fold change: UHR/HBR log2 ratios of the ERCC subgroups (4 : 1, 1 : 1, 2 : 3, 1 : 2) correlate with the expected ones at <!--ev:rnaseq_fc_pearson-->0.984<!--/ev--> after the mRNA-fraction offset is removed;
- counts, BAM records and every report number are identical at 4 and 2 threads; a repeated run gives a byte-identical BAM once STAR's output is re-blocked by htslib (STAR picks its sorting bins from whichever thread fills a buffer first).

featureCounts is built from source together with its test suite (<!--ev:featurecounts_tests_passed-->52<!--/ev--> checks pass). Details (in Russian): `docs/RNASEQ.md`.

## Run

```bash
make setup && source .venv/bin/activate
```

```bash
make image && make data && make run
```

```bash
make repro
```

```bash
make callers && make metric
```

```bash
make rnaseq-image rnaseq-data rnaseq
```

```bash
make depth aggregation
```

The report is `results/run/HG002.report.html`: confidence intervals (Wilson; Monte Carlo for F1), stratified accuracy, depth vs Poisson and negative binomial, an 8-oxoG test on the substitution spectrum, and wall time / peak memory of every step.

## What is in the repository

- `cwl/` — <!--ev:cwl_tools-->19<!--/ev--> CommandLineTools, the WGS workflow, two caller workflows (Strelka2, DeepVariant) on an existing BAM and the RNA-seq workflow; `bin/measure.py` is staged into every step and records time, CPU and process-tree peak memory as a regular CWL output.
- `docker/tools/`, `docker/rnaseq/` — multi-stage builds from source, base image by digest, Debian packages from snapshot.debian.org, a sha256 for every download.
- `slurm/` — sbatch for cwltool + Apptainer, Toil leader, cohort array; tested on Slurm 23.11 with slurmdbd.
- `scripts/` — data preparation with integrity checks, reproducibility check, report, SQLite results database, evidence and claims linting, the Pages site and its browser checks.
- `docker/fastp-isize/` — fastp 1.4.0 built from source as released and with a three-line patch: the released fastp builds its insert-size histogram in worker thread 0 only, so at 4 threads it sees <!--ev:fastp_isize_rna_share_t4-->25<!--/ev--> % of the pairs and the reported peak depends on the thread count.
- `docs/` — a one-page summary (`SPRAVKA.md`), methodology, results, reproducibility, a debugging log of <!--ev:debug_cases-->23<!--/ev--> real issues, cluster and GitLab guides, ADRs, literature (in Russian).

Limits are listed in [LIMITS.md](LIMITS.md): one WGS sample and one 2 Mb region, no GATK, RNA-seq on chr22 reads only and without a differential expression test.

License: MIT.
