#!/usr/bin/env bash
# usage: smoke_test.sh <health-url> <expected-version>
# Passes only when the NEW version answers - an old healthy revision is not a pass.
set -u
URL="$1"; EXPECTED="$2"
for i in $(seq 1 18); do
  body=$(curl -sS --max-time 10 "$URL" 2>&1 || true)
  echo "attempt $i: $body"
  if echo "$body" | grep -Eq "\"version\": ?\"$EXPECTED\""; then echo "Smoke test passed"; exit 0; fi
  sleep 10
done
echo "::error::Smoke test failed: $URL never reported version $EXPECTED"
exit 1
