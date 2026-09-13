#!/usr/bin/env sh
# Refuse a commit that stages a secret-bearing file or a key-shaped string.
# Run it before every commit: scripts/check_secrets.sh && git commit ...
set -eu
if git diff --cached --name-only | grep -Ei '(^|/)\.env$|\.png$|friday-studio|(^|/)kelbro/|(^|/)DORA/' ; then
  echo "check_secrets: refusing — a listed file above must never be committed" >&2
  exit 1
fi
if git diff --cached | grep -E '^\+' | grep -E 'gsk_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}|sk-ant-[A-Za-z0-9_-]{20,}|xox[bp]-[A-Za-z0-9-]{20,}|lin_api_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}' ; then
  echo "check_secrets: refusing — the staged diff adds something shaped like a key" >&2
  exit 1
fi
echo "check_secrets: ok"
