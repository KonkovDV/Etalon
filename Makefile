# hg002-mini-wgs — one entry point for every routine action. `make help` lists them.
SHELL := /bin/bash
.ONESHELL:
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

TOOLS_IMAGE  ?= hg002-mini/tools:1.0.0
RNASEQ_IMAGE ?= hg002-mini/rnaseq:1.0.0
FASTP_ISIZE_IMAGE ?= hg002-mini/fastp-isize:1.4.0
HAPPY_IMAGE  ?= quay.io/biocontainers/hap.py@sha256:d63b963a6cb01b4830393b22369e7b91d298e4156dde353739e74e4cfa4f96d0
THREADS      ?= 4
OUT          ?= results/run
RNASEQ_OUT   ?= results/rnaseq
# Subread source (SourceForge): fetched by scripts/fetch_source.sh, not by ADD (D-19)
SUBREAD_SHA256 := 6392d7c66831cdd767e58251892a79a51b6fab8ed0ba9671ad5e85ff1ab01eaa
SUBREAD_PATH   := project/subread/subread-2.1.1/subread-2.1.1-source.tar.gz
# Extra `docker run` / `docker build` flags, e.g. for a corporate proxy:
#   DOCKER_RUN_OPTS='--network host -e https_proxy -e CURL_CA_BUNDLE=/ca.crt -v /etc/ssl/ca.crt:/ca.crt:ro'
DOCKER_RUN_OPTS   ?=
DOCKER_BUILD_OPTS ?=
# Network that re-signs TLS with its own root certificate (TLS inspection, a
# national root CA): `make image data EXTRA_CA=/path/to/ca.pem` with https_proxy set.
# The build gets the root as a BuildKit secret (never stored in a layer), the data
# step gets it read-only for curl and htslib. See docs/OFFLINE.md.
EXTRA_CA ?=
ifneq ($(strip $(EXTRA_CA)),)
CA_FILE := $(abspath $(EXTRA_CA))
DOCKER_BUILD_OPTS += --network host --secret id=extra_ca,src=$(CA_FILE) \
  --build-arg SNAPSHOT_URL=https://snapshot.debian.org \
  --build-arg https_proxy --build-arg HTTPS_PROXY \
  --build-arg no_proxy=localhost,127.0.0.1 --build-arg NO_PROXY=localhost,127.0.0.1
DOCKER_RUN_OPTS += --network host -e https_proxy -e HTTPS_PROXY -e no_proxy=localhost,127.0.0.1 \
  -e CURL_CA_BUNDLE=/etc/ssl/extra-ca.pem -v $(CA_FILE):/etc/ssl/extra-ca.pem:ro
endif

.PHONY: help
help: ## show this list
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z0-9_.-]+:.*## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: setup
setup: ## create .venv with cwltool and dev tools
	python3 -m venv .venv
	.venv/bin/pip install -q -r requirements-dev.txt
	@echo "activate with: source .venv/bin/activate"

.PHONY: image
image: ## build the tools image from source (htslib/samtools/bcftools + their test suites)
	docker build $(DOCKER_BUILD_OPTS) --build-arg RUN_TESTS=1 -t $(TOOLS_IMAGE) docker/tools
	docker pull $(HAPPY_IMAGE)

.PHONY: data
data: ## download the HG002 region, GIAB truth sets and stratifications into data/
	docker run --rm $(DOCKER_RUN_OPTS) -u $$(id -u):$$(id -g) -v "$$PWD":/work -w /work \
	  $(TOOLS_IMAGE) scripts/prepare_data.sh
	(cd data && sha256sum -c --quiet MANIFEST.sha256) && echo "data verified"

.PHONY: run
run: ## run the CWL workflow -> $(OUT)/HG002.report.html
	scripts/run_pipeline.sh -o $(OUT) threads=$(THREADS)
	python3 scripts/qc_gate.py $(OUT)/HG002.report.json

.PHONY: repro
repro: ## run twice (4 and 2 threads) and compare VCF/BAM/hap.py byte for byte
	scripts/check_reproducibility.sh

.PHONY: callers
callers: ## Strelka2 and DeepVariant on the BAM of $(OUT), compared with bcftools -> results/callers/compare.md
	for c in strelka2 deepvariant; do
	  scripts/run_pipeline.sh -w cwl/workflows/call-$$c.cwl -o results/callers/$$c \
	    bam=$(OUT)/HG002.bam reference=data/ref/ref.fa threads=$(THREADS)
	done
	python3 scripts/compare_callers.py bcftools=$(OUT) strelka2=results/callers/strelka2 \
	  deepvariant=results/callers/deepvariant --base strelka2 \
	  --json results/callers/compare.json --md results/callers/compare.md
	@echo "comparison: results/callers/compare.md"

.PHONY: metric
metric: ## genotype-concordance metric of patent RU 2846268 next to GA4GH -> results/metrics/patent_metric.md
	mkdir -p results/metrics
	python3 scripts/concordance.py --truth-dir data/truth --ref data/ref/ref.fa --strata data/strat \
	  --compare results/callers/compare.json \
	  --json results/metrics/patent_metric.json --md results/metrics/patent_metric.md \
	  bcftools=$(OUT)/HG002.vcf.gz strelka2=results/callers/strelka2/HG002.strelka2.vcf.gz \
	  deepvariant=results/callers/deepvariant/HG002.deepvariant.vcf.gz
	@echo "metric: results/metrics/patent_metric.md"

.PHONY: rnaseq-image
rnaseq-image: ## build the RNA-seq image: STAR 2.7.11b, featureCounts built from source + its tests
	scripts/fetch_source.sh $(SUBREAD_SHA256) docker/rnaseq/vendor/subread-2.1.1-source.tar.gz \
	  https://downloads.sourceforge.net/$(SUBREAD_PATH) https://master.dl.sourceforge.net/$(SUBREAD_PATH)
	docker build $(DOCKER_BUILD_OPTS) --build-arg RUN_TESTS=1 -t $(RNASEQ_IMAGE) docker/rnaseq

.PHONY: rnaseq-data
rnaseq-data: ## download UHR/HBR RNA-seq with ERCC spike-ins, chr22 + ERCC92 reference, GENCODE, ERCC truth
	docker run --rm $(DOCKER_RUN_OPTS) -u $$(id -u):$$(id -g) -v "$$PWD":/work -w /work \
	  $(TOOLS_IMAGE) scripts/prepare_rnaseq_data.sh
	(cd data/rnaseq && sha256sum -c --quiet MANIFEST.sha256) && echo "rnaseq data verified"

.PHONY: rnaseq
rnaseq: ## RNA-seq workflow (STAR + featureCounts) checked against ERCC -> $(RNASEQ_OUT)/rnaseq.report.md
	scripts/run_pipeline.sh -w cwl/workflows/rnaseq.cwl -j cwl/jobs/rnaseq-uhr-hbr.yml -o $(RNASEQ_OUT) threads=$(THREADS)
	python3 scripts/qc_gate.py $(RNASEQ_OUT)/rnaseq.report.json

.PHONY: fastp-isize-image
fastp-isize-image: ## fastp 1.4.0 from source: as released and with the insert-size patch (D-23)
	docker build $(DOCKER_BUILD_OPTS) -t $(FASTP_ISIZE_IMAGE) docker/fastp-isize

.PHONY: fastp-isize
fastp-isize: ## release vs patched fastp on 1-4 threads -> results/fastp_isize_threads.md
	scripts/check_fastp_isize.sh results/fastp_isize_threads.md

.PHONY: depth
depth: ## accuracy vs depth: thin reads to 5-35x, three callers at each depth (~30 min, 4 threads) -> docs/results/depth
	scripts/depth_series.sh results/depth
	python3 scripts/depth_curve.py results/depth --json docs/results/depth/curve.json --md docs/results/depth/curve.md
	python3 scripts/render_depth_figure.py

.PHONY: cram
cram: ## BAM vs CRAM 3.0, 3.1 and 3.1 archive: size, time, same records and calls -> docs/results/cram
	scripts/check_cram.sh results/cram $(OUT)/HG002.bam data/ref/ref.fa
	python3 scripts/cram_report.py results/cram --json docs/results/cram/cram.json --md docs/results/cram/cram.md

.PHONY: aggregation
aggregation: ## frequency database: variant representation across callers and AN from gVCF (after make depth)
	scripts/compare_representation.sh results/representation \
	  bcftools=results/depth/f1.0_s1/run/HG002.vcf.gz \
	  strelka2=results/depth/f1.0_s1/strelka2/HG002.strelka2.vcf.gz \
	  deepvariant=results/depth/f1.0_s1/deepvariant/HG002.deepvariant.vcf.gz
	mkdir -p docs/results/aggregation
	cp results/representation/representation.json results/representation/representation.md docs/results/aggregation/
	python3 scripts/callable_sites.py results/depth \
	  --json docs/results/aggregation/callable.json --md docs/results/aggregation/callable.md

.PHONY: db
db: ## load result directories into results/results.sqlite and print the summary
	python3 scripts/results_db.py ingest $$(ls -d results/*/ | grep -v '\.work/$$')
	python3 scripts/results_db.py summary

.PHONY: test
test: ## unit tests with coverage; fails on skipped tests
	python3 -m pytest --junitxml=var/junit.xml --cov=bin --cov=scripts --cov-report=term-missing
	python3 scripts/check_no_skips.py var/junit.xml

.PHONY: lint
lint: ## CWL validation, ruff, shellcheck, claims linter
	for f in cwl/tools/*.cwl cwl/workflows/*.cwl; do cwltool --validate "$$f" >/dev/null; done && echo "CWL: all valid"
	ruff check bin scripts tests
	ruff format --check bin scripts tests
	shellcheck -x scripts/*.sh slurm/*.sh slurm/*.sbatch
	python3 scripts/lint_claims.py
	python3 scripts/check_links.py

.PHONY: evidence
evidence: ## rebuild evidence.json from tests and the reference run
	python3 scripts/build_evidence.py

.PHONY: figures
figures: ## rebuild evidence.json and the SVG figures in docs/assets (they show the test count, hence the order)
	python3 scripts/build_evidence.py --no-tests
	python3 scripts/render_infographic.py
	python3 scripts/render_rnaseq_figure.py
	python3 scripts/render_depth_figure.py
	python3 scripts/build_evidence.py

.PHONY: site
site: ## build the Pages site into public/ and check it in a browser (8 devices x 2 themes, WCAG 2.2 AA)
	python3 scripts/build_site.py --out public
	(cd scripts && npm ci --no-audit --no-fund)  # subshell: with .ONESHELL a bare cd would move the next line too
	node scripts/check_site.js public

.PHONY: slurm
slurm: ## submit the one-node Slurm job (cwltool + Apptainer)
	mkdir -p logs && sbatch slurm/run_cwltool_apptainer.sbatch

.PHONY: clean
clean: ## remove run outputs (keeps data/ and the images)
	rm -rf results var logs public .pytest_cache .ruff_cache .coverage
