# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
#
# Etalon / RNA-seq image
#
#   STAR 2.7.11b            -> official static x86-64 release binary (sha256-verified)
#   Subread 2.1.1           -> featureCounts compiled from the source tarball (sha256-verified);
#                              its featureCounts test suite runs at build time with RUN_TESTS=1
#   python3                 -> runtime for bin/measure.py
#
# The same reproducibility rules as docker/tools/Dockerfile: base image by digest,
# Debian packages from snapshot.debian.org, a sha256 for every download, compilers
# only in the builder stage. `make rnaseq-image` builds it; behind a proxy that
# re-signs TLS pass the root certificate exactly as for the tools image:
#   make rnaseq-image EXTRA_CA=/path/to/ca.pem          (docs/OFFLINE.md)
#
# The Subread tarball is not fetched with ADD: SourceForge mirrors cut transfers
# off and ADD cannot retry or resume (D-19). `make rnaseq-image` downloads it into
# vendor/ with scripts/fetch_source.sh (retries, resume, several mirrors, sha256),
# and the build checks the same sha256 again before unpacking.
#
# Why STAR comes as the release binary and is safe on any x86-64 node: the
# Makefile adds -mavx2 (CXXFLAGS_SIMD) to opal.cpp only, and opal is called only
# by --clipAdapterType CellRanger4. objdump of this binary finds AVX2 code in the
# opal functions and in glibc routines that pick their variant by CPUID at run
# time, nowhere else (docs/DEBUGGING.md, D-17). The bulk RNA-seq run here never
# enters opal.
#
# Subread's test scripts print PASS/FAILED but always exit 0, so the build counts
# the lines itself and fails on any FAILED (docs/DEBUGGING.md, D-18).

ARG BASE_IMAGE=debian:trixie-slim@sha256:8aa5a7bf5a1955bddbe7d74fcdd0b91ab30e74362a8b73af672b0481b35b44a0
ARG DEBIAN_SNAPSHOT=20261123T000000Z
ARG SNAPSHOT_URL=http://snapshot.debian.org

############################  builder  ########################################
FROM ${BASE_IMAGE} AS builder
ARG DEBIAN_SNAPSHOT
ARG SNAPSHOT_URL
ARG RUN_TESTS=0
ARG STAR_VERSION=2.7.11b
ARG SUBREAD_VERSION=2.1.1
ARG SUBREAD_SHA256=6392d7c66831cdd767e58251892a79a51b6fab8ed0ba9671ad5e85ff1ab01eaa

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN --mount=type=secret,id=extra_ca,mode=0444 \
    apt_opts=() \
 && if [ -s /run/secrets/extra_ca ]; then apt_opts=(-o "Acquire::https::CaInfo=/run/secrets/extra_ca"); fi \
 && sed -i -E \
      -e "s|^URIs: http://deb.debian.org/debian$|URIs: ${SNAPSHOT_URL}/archive/debian/${DEBIAN_SNAPSHOT}|" \
      -e "s|^URIs: http://deb.debian.org/debian-security$|URIs: ${SNAPSHOT_URL}/archive/debian-security/${DEBIAN_SNAPSHOT}|" \
      /etc/apt/sources.list.d/debian.sources \
 && echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99snapshot \
 && echo 'Acquire::Retries "5";'               >> /etc/apt/apt.conf.d/99snapshot \
 && apt-get "${apt_opts[@]}" update \
 && apt-get "${apt_opts[@]}" install -y --no-install-recommends \
      build-essential zlib1g-dev unzip ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ADD --checksum=sha256:9ec60251de46c7c83087c06f6a1acab71ad09137d991b485e02be819cb8ad136 \
    https://github.com/alexdobin/STAR/releases/download/${STAR_VERSION}/STAR_${STAR_VERSION}.zip /src/
COPY vendor/subread-${SUBREAD_VERSION}-source.tar.gz /src/

WORKDIR /src
RUN echo "${SUBREAD_SHA256}  subread-${SUBREAD_VERSION}-source.tar.gz" | sha256sum -c - \
 && unzip -q STAR_${STAR_VERSION}.zip \
 && tar -xzf subread-${SUBREAD_VERSION}-source.tar.gz

# Subread: the Makefile builds every tool; only featureCounts is installed.
WORKDIR /src/subread-${SUBREAD_VERSION}-source/src
RUN make -f Makefile.Linux

# The test scripts call ../../bin/featureCounts and never fail the shell, so the
# PASS/FAILED verdicts are counted here (one line can hold two, e.g. junction
# counting checks the counts and the .jcounts file). ANSI colour codes are stripped first.
WORKDIR /src/subread-${SUBREAD_VERSION}-source/test/featureCounts
RUN if [ "${RUN_TESTS}" = "1" ]; then \
      bash featureCounts-test.sh 2>&1 | sed -E 's/\x1b\[[0-9;]*m//g' | tee /src/featureCounts-tests.log; \
      passed="$(grep -o 'PASS' /src/featureCounts-tests.log | wc -l)"; \
      failed="$(grep -o 'FAILED' /src/featureCounts-tests.log | wc -l)"; \
      echo "featureCounts tests: passed ${passed}, failed ${failed}"; \
      [ "${failed}" = "0" ] && [ "${passed}" -gt 0 ]; \
    fi

WORKDIR /src
RUN install -D -m 755 STAR_${STAR_VERSION}/Linux_x86_64_static/STAR /opt/rnaseq/bin/STAR \
 && install -m 755 subread-${SUBREAD_VERSION}-source/bin/featureCounts /opt/rnaseq/bin/featureCounts \
 && strip --strip-unneeded /opt/rnaseq/bin/featureCounts \
 && { \
      echo "STAR	$(/opt/rnaseq/bin/STAR --version) (release ${STAR_VERSION}, Linux_x86_64_static)"; \
      echo "featureCounts	$(/opt/rnaseq/bin/featureCounts -v 2>&1 | grep -o 'v[0-9.]*' | head -1) (Subread ${SUBREAD_VERSION}, built from source)"; \
    } > /opt/rnaseq/TOOL_VERSIONS.tsv \
 && cat /opt/rnaseq/TOOL_VERSIONS.tsv

############################  runtime  ########################################
FROM ${BASE_IMAGE} AS runtime
ARG DEBIAN_SNAPSHOT
ARG SNAPSHOT_URL
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

LABEL org.opencontainers.image.title="Etalon RNA-seq tools" \
      org.opencontainers.image.description="STAR 2.7.11b (release binary), featureCounts from Subread 2.1.1 (built from source)" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.base.name="debian:trixie-slim@sha256:8aa5a7bf5a1955bddbe7d74fcdd0b91ab30e74362a8b73af672b0481b35b44a0"

RUN --mount=type=secret,id=extra_ca,mode=0444 \
    apt_opts=() \
 && if [ -s /run/secrets/extra_ca ]; then apt_opts=(-o "Acquire::https::CaInfo=/run/secrets/extra_ca"); fi \
 && sed -i -E \
      -e "s|^URIs: http://deb.debian.org/debian$|URIs: ${SNAPSHOT_URL}/archive/debian/${DEBIAN_SNAPSHOT}|" \
      -e "s|^URIs: http://deb.debian.org/debian-security$|URIs: ${SNAPSHOT_URL}/archive/debian-security/${DEBIAN_SNAPSHOT}|" \
      /etc/apt/sources.list.d/debian.sources \
 && echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99snapshot \
 && echo 'Acquire::Retries "5";'               >> /etc/apt/apt.conf.d/99snapshot \
 && apt-get "${apt_opts[@]}" update \
 && apt-get "${apt_opts[@]}" install -y --no-install-recommends \
      zlib1g python3 procps \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/rnaseq /opt/rnaseq

ENV PATH=/opt/rnaseq/bin:${PATH} \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1

# Smoke test: both binaries start (fails the build otherwise).
RUN STAR --version \
 && featureCounts -v 2>&1 | grep -q 'featureCounts v' \
 && python3 -c 'import json, resource, subprocess'

# No ENTRYPOINT/CMD: CWL runners supply the full command line.
