#!/usr/bin/env bash
# Download a source archive with retries, resume and mirror fallback; keep it only
# if its sha256 matches.
#
#   scripts/fetch_source.sh SHA256 DEST URL [URL ...]
#
# Docker's `ADD --checksum` makes one attempt and cannot resume. SourceForge
# mirrors behind a proxy cut transfers off midway, so ADD failed with a different
# digest on every try (docs/DEBUGGING.md, D-19). curl retries, resumes a partial
# file (-C -) and moves on to the next mirror; the checksum decides what is kept.
# Honours https_proxy and CURL_CA_BUNDLE like every other download in the repo.
set -euo pipefail

if [[ $# -lt 3 ]]; then
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
fi
sha="$1" dest="$2"
shift 2

log() { printf '[fetch_source] %s\n' "$*" >&2; }
matches() { [[ -s "$1" ]] && echo "${sha}  $1" | sha256sum -c --quiet - >/dev/null 2>&1; }

if matches "${dest}"; then
  log "$(basename "${dest}"): present, sha256 ok"
  exit 0
fi
mkdir -p "$(dirname "${dest}")"
part="${dest}.part"
for url in "$@"; do
  rm -f "${part}"  # never resume bytes that came from another mirror
  for attempt in 1 2 3; do
    log "$(basename "${dest}"): ${url} (attempt ${attempt})"
    rc=0
    curl -fL --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 30 \
      -C - -o "${part}" "${url}" || rc=$?
    if (( rc == 0 )); then
      if matches "${part}"; then
        mv "${part}" "${dest}"
        log "$(basename "${dest}"): sha256 ok"
        exit 0
      fi
      log "complete download with a wrong sha256: discarded"
      rm -f "${part}"
    elif (( rc == 33 )); then  # the server cannot resume: start over
      rm -f "${part}"
    fi  # any other error: keep the partial file, the next attempt resumes it
  done
done
rm -f "${part}"
log "ERROR: no source gave $(basename "${dest}") with sha256 ${sha}"
exit 1
