# syntax=docker/dockerfile:1.7@sha256:a57df69d0ea827fb7266491f2813635de6f17269be881f696fbfdf2d83dda33e
#
# fastp 1.4.0 built from source twice: as released and with one patch, to show
# that the insert-size histogram of the release depends on the thread count and
# that the patch removes the dependence (docs/DEBUGGING.md, D-23).
#
#   /opt/fastp/bin/fastp.release   tag v1.4.0, commit ee125a5, unchanged
#   /opt/fastp/bin/fastp.patched   the same commit + fastp-1.4.0-isize-all-threads.patch
#
# The pipeline does not use this image: it keeps the official fastp binary of the
# tools image. This one exists only for scripts/check_fastp_isize.sh.
#
# Build: make fastp-isize-image   (behind a TLS-inspecting proxy: EXTRA_CA=/path/to/ca.pem)

ARG BASE_IMAGE=debian:trixie-slim@sha256:8aa5a7bf5a1955bddbe7d74fcdd0b91ab30e74362a8b73af672b0481b35b44a0
ARG DEBIAN_SNAPSHOT=20261123T000000Z
ARG SNAPSHOT_URL=http://snapshot.debian.org

FROM ${BASE_IMAGE} AS builder
ARG DEBIAN_SNAPSHOT
ARG SNAPSHOT_URL
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
      build-essential pkg-config libisal-dev libdeflate-dev libhwy-dev patch ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# A git source pinned by the full commit hash of the v1.4.0 tag.
ADD https://github.com/OpenGene/fastp.git#ee125a52fddae9d8189e13cd8a33ad04988a1351 /src/release
COPY fastp-1.4.0-isize-all-threads.patch /src/

RUN cp -a /src/release /src/patched \
 && patch -d /src/patched -p1 < /src/fastp-1.4.0-isize-all-threads.patch \
 && make -C /src/release -j"$(nproc)" \
 && make -C /src/patched -j"$(nproc)" \
 && install -D -m 755 /src/release/fastp /opt/fastp/bin/fastp.release \
 && install -m 755 /src/patched/fastp /opt/fastp/bin/fastp.patched

FROM ${BASE_IMAGE} AS runtime
ARG DEBIAN_SNAPSHOT
ARG SNAPSHOT_URL
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
LABEL org.opencontainers.image.title="fastp 1.4.0, release and insert-size patch" \
      org.opencontainers.image.licenses="MIT"

RUN --mount=type=secret,id=extra_ca,mode=0444 \
    apt_opts=() \
 && if [ -s /run/secrets/extra_ca ]; then apt_opts=(-o "Acquire::https::CaInfo=/run/secrets/extra_ca"); fi \
 && sed -i -E \
      -e "s|^URIs: http://deb.debian.org/debian$|URIs: ${SNAPSHOT_URL}/archive/debian/${DEBIAN_SNAPSHOT}|" \
      -e "s|^URIs: http://deb.debian.org/debian-security$|URIs: ${SNAPSHOT_URL}/archive/debian-security/${DEBIAN_SNAPSHOT}|" \
      /etc/apt/sources.list.d/debian.sources \
 && echo 'Acquire::Check-Valid-Until "false";' > /etc/apt/apt.conf.d/99snapshot \
 && apt-get "${apt_opts[@]}" update \
 && apt-get "${apt_opts[@]}" install -y --no-install-recommends libisal2 libdeflate0 libhwy1t64 python3 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=builder /opt/fastp /opt/fastp
ENV PATH=/opt/fastp/bin:${PATH}
RUN fastp.release --version && fastp.patched --version
