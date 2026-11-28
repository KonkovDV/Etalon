#!/usr/bin/env bash
# Local alternative to the GitHub Action: make `git push` update GitHub and GitLab at once.
#
#   scripts/setup_gitlab_mirror.sh git@gitlab.com:<group>/hg002-mini-wgs.git
#
# Adds a second push URL to `origin` (fetch stays on GitHub) and a `gitlab`
# remote for explicit pushes. Idempotent: re-running does not duplicate URLs.
set -euo pipefail

GITLAB_URL="${1:?usage: $0 <gitlab-repo-url>}"
ORIGIN_URL="$(git remote get-url origin)"

if ! git remote get-url gitlab >/dev/null 2>&1; then
  git remote add gitlab "${GITLAB_URL}"
fi

push_urls="$(git remote get-url --push --all origin)"
if ! grep -qxF "${ORIGIN_URL}" <<<"${push_urls}"; then
  git remote set-url --add --push origin "${ORIGIN_URL}"
fi
if ! grep -qxF "${GITLAB_URL}" <<<"${push_urls}"; then
  git remote set-url --add --push origin "${GITLAB_URL}"
fi

echo "origin pushes to:"
git remote get-url --push --all origin | sed 's/^/  /'
echo "first sync:  git push gitlab --all && git push gitlab --tags"
