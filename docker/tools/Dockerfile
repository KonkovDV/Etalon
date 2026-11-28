# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
#
# hg002-mini-wgs / tools image
#
#   htslib, samtools, bcftools  -> compiled from release tarballs (sha256-verified)
#   bwa-mem2, fastp             -> official x86-64 release binaries (sha256-verified)
#   python3                     -> runtime for bin/measure.py and report scripts
#
# Reproducibility decisions:
#   * base image pinned by manifest digest, not by a moving tag;
#   * Debian packages come from snapshot.debian.org at the same timestamp the
#     base image was built from, so `apt-get install` resolves to the same
#     package versions next year as today;
#   * every downloaded artefact is checked with ADD --checksum (BuildKit fails
#     the build on mismatch);
#   * builder and runtime stages are separate: compilers never reach runtime.
#
# Build:   docker build -t hg002-mini/tools:1.0.0 docker/tools
# Tests:   docker build --build-arg RUN_TESTS=1 ...   (runs `make test` for all three)
# Behind a corporate proxy pass http_proxy/https_proxy AND no_proxy=localhost,127.0.0.1:
#   htslib's ref-cache test starts an HTTP server on localhost; without no_proxy
#   libcurl sends that request to the proxy and the test fails (seen in practice).
#
# Behind a proxy that re-signs TLS with its own root (TLS inspection, a national
# root CA, an air-gapped mirror) give apt that root as a BuildKit secret and
# switch the snapshot mirror to https. The certificate is used only while apt
# runs and is never written into a layer:
#   docker build --network host --secret id=extra_ca,src=/path/to/ca.pem \
#     --build-arg SNAPSHOT_URL=https://snapshot.debian.org ...
# `make image EXTRA_CA=/path/to/ca.pem` does exactly this (docs/OFFLINE.md).

ARG BASE_IMAGE=debian:trixie-slim@sha256:8aa5a7bf5a1955bddbe7d74fcdd0b91ab30e74362a8b73af672b0481b35b44a0
# Snapshot that matches the base image (see the comment in /etc/apt/sources.list.d/debian.sources)
ARG DEBIAN_SNAPSHOT=20261123T000000Z
# Plain http by default: apt checks the signed Release files either way.
ARG SNAPSHOT_URL=http://snapshot.debian.org

############################  builder  ########################################
FROM ${BASE_IMAGE} AS builder
ARG DEBIAN_SNAPSHOT
ARG SNAPSHOT_URL
ARG RUN_TESTS=0

ARG HTSLIB_VERSION=1.25
ARG SAMTOOLS_VERSION=1.25
ARG BCFTOOLS_VERSION=1.25

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Pin apt to the snapshot. Check-Valid-Until is off because snapshot Release
# files are, by definition, older than their Valid-Until stamp.
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
      build-essential autoconf automake perl \
      zlib1g-dev libbz2-dev liblzma-dev libdeflate-dev \
      libcurl4-openssl-dev libssl-dev libncurses-dev \
      bzip2 ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Release tarballs: sha256 recorded at the time of pinning (see docs/provenance.md).
ADD --checksum=sha256:158c271e4e2986bb2dd11283b640edc10c56695b293df77a109ce99480303730 \
    https://github.com/samtools/htslib/releases/download/${HTSLIB_VERSION}/htslib-${HTSLIB_VERSION}.tar.bz2 /src/
ADD --checksum=sha256:8bbd2b3cb447953149a74ab0b00e3ec4e88a789a27b8373a31fa6b5b2dee02b1 \
    https://github.com/samtools/samtools/releases/download/${SAMTOOLS_VERSION}/samtools-${SAMTOOLS_VERSION}.tar.bz2 /src/
ADD --checksum=sha256:f96e583d2315998645bb56756f1c8f230c489512db2655b0f623198ebc8a2d99 \
    https://github.com/samtools/bcftools/releases/download/${BCFTOOLS_VERSION}/bcftools-${BCFTOOLS_VERSION}.tar.bz2 /src/
ADD --checksum=sha256:112f3a3ebf3f8c2377f52d61446ead392c4a98ecf89e7629617d3ed16f4e73cb \
    https://github.com/bwa-mem2/bwa-mem2/releases/download/v2.3/bwa-mem2-2.3_x64-linux.tar.bz2 /src/
ADD --checksum=sha256:e56c3218b76cc1d6d8a7a32315fa6a41407f5d271fe561fc62cee15941190844 --chmod=755 \
    https://opengene.org/fastp/fastp.1.4.0 /opt/bin/fastp

WORKDIR /src

RUN tar -xjf htslib-${HTSLIB_VERSION}.tar.bz2 \
 && tar -xjf samtools-${SAMTOOLS_VERSION}.tar.bz2 \
 && tar -xjf bcftools-${BCFTOOLS_VERSION}.tar.bz2 \
 && tar -xjf bwa-mem2-2.3_x64-linux.tar.bz2

# htslib: libcurl (http/https/ftp), S3 and GCS backends + libdeflate (faster BGZF).
# Installed into /opt/hts so the runtime stage can copy one tree.
WORKDIR /src/htslib-${HTSLIB_VERSION}
RUN ./configure --prefix=/opt/hts --enable-libcurl --enable-s3 --enable-gcs --with-libdeflate \
 && make -j"$(nproc)" \
 && if [ "${RUN_TESTS}" = "1" ]; then make test; fi \
 && make install

# samtools/bcftools are linked against the htslib built above (not their bundled copy),
# so all three tools share one, tested libhts.so. Their test suites call bgzip/tabix
# from PATH, hence /opt/hts/bin first.
ENV PATH=/opt/hts/bin:${PATH}
WORKDIR /src/samtools-${SAMTOOLS_VERSION}
RUN ./configure --prefix=/opt/hts --with-htslib=/opt/hts --without-curses \
      LDFLAGS="-Wl,-rpath,/opt/hts/lib" \
 && make -j"$(nproc)" \
 && if [ "${RUN_TESTS}" = "1" ]; then make test; fi \
 && make install

WORKDIR /src/bcftools-${BCFTOOLS_VERSION}
RUN ./configure --prefix=/opt/hts --with-htslib=/opt/hts \
      LDFLAGS="-Wl,-rpath,/opt/hts/lib" \
 && make -j"$(nproc)" \
 && if [ "${RUN_TESTS}" = "1" ]; then make test; fi \
 && make install

# bwa-mem2 ships one launcher + one binary per SIMD level; the launcher picks the
# best one for the CPU at run time (sse41 / sse42 / avx / avx2 / avx512bw).
# NB: the official v2.3 release binaries print "2.2.1" for `bwa-mem2 version`
# (upstream did not bump the version string; NEWS.md also stops at 2.2.1), so
# the version is pinned by the release tag + tarball sha256, not by self-report.
WORKDIR /src
RUN install -m 755 bwa-mem2-2.3_x64-linux/bwa-mem2* /opt/hts/bin/ \
 && install -m 755 /opt/bin/fastp /opt/hts/bin/fastp \
 && strip --strip-unneeded /opt/hts/bin/samtools /opt/hts/bin/bcftools /opt/hts/bin/bgzip \
      /opt/hts/bin/tabix /opt/hts/bin/htsfile /opt/hts/bin/fastp /opt/hts/lib/libhts.so.*

# Freeze what was actually built into the image (read by the report step).
RUN { \
      echo "htslib	$(/opt/hts/bin/htsfile --version | head -1 | awk '{print $NF}')"; \
      echo "samtools	$(/opt/hts/bin/samtools --version | head -1 | awk '{print $2}')"; \
      echo "bcftools	$(/opt/hts/bin/bcftools --version | head -1 | awk '{print $2}')"; \
      echo "bwa-mem2	2.3 (release v2.3 tarball; binary self-reports $(/opt/hts/bin/bwa-mem2 version 2>/dev/null | tail -1))"; \
      echo "fastp	$(/opt/hts/bin/fastp --version 2>&1 | awk '{print $2}')"; \
    } > /opt/hts/TOOL_VERSIONS.tsv \
 && cat /opt/hts/TOOL_VERSIONS.tsv

############################  runtime  ########################################
FROM ${BASE_IMAGE} AS runtime
ARG DEBIAN_SNAPSHOT
ARG SNAPSHOT_URL
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

LABEL org.opencontainers.image.title="hg002-mini-wgs tools" \
      org.opencontainers.image.description="htslib/samtools/bcftools 1.25 (built from source), bwa-mem2 2.3, fastp 1.4.0" \
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
      zlib1g libbz2-1.0 liblzma5 libdeflate0 libcurl4t64 libssl3t64 \
      ca-certificates curl python3 procps \
 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/hts /opt/hts

ENV PATH=/opt/hts/bin:${PATH} \
    BCFTOOLS_PLUGINS=/opt/hts/libexec/bcftools \
    LC_ALL=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1

# Smoke test: every binary starts and links (fails the build otherwise).
RUN samtools --version | head -1 \
 && bcftools --version | head -1 \
 && bgzip --version | head -1 \
 && bwa-mem2 version \
 && fastp --version \
 && bcftools plugin -l | grep -q fill-tags \
 && python3 -c 'import json, resource, subprocess, sqlite3'

# No ENTRYPOINT/CMD: CWL runners supply the full command line.
