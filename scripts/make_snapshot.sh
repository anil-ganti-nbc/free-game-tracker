#!/bin/sh
# Produces an immutable, hashed source snapshot for deployment - the
# provenance mechanism for this migration phase while GitHub is not yet in
# use. No commit SHA involved; this tarball + its SHA-256 IS the record of
# exactly what was deployed.
#
# Usage: scripts/make_snapshot.sh <environment> [sequence]
#   e.g. scripts/make_snapshot.sh hetzner        -> auto-picks next NN
#        scripts/make_snapshot.sh hetzner 01     -> explicit sequence
#
# Output: snapshots/free-game-tracker_<date>_<environment>-<NN>.tar.gz
#         plus a .sha256 file alongside it.
set -eu
cd "$(dirname "$0")/.."

CLANK_NAME="free-game-tracker"
ENVIRONMENT="${1:?usage: make_snapshot.sh <environment> [sequence]}"
DATE="$(date -u +%Y-%m-%d)"
OUT_DIR="snapshots"
mkdir -p "$OUT_DIR"

if [ -n "${2:-}" ]; then
  SEQ="$2"
else
  SEQ=1
  while [ -f "$OUT_DIR/${CLANK_NAME}_${DATE}_${ENVIRONMENT}-$(printf '%02d' "$SEQ").tar.gz" ]; do
    SEQ=$((SEQ + 1))
  done
  SEQ="$(printf '%02d' "$SEQ")"
fi

DEPLOYMENT_ID="${CLANK_NAME}_${DATE}_${ENVIRONMENT}-${SEQ}"
ARCHIVE="$OUT_DIR/${DEPLOYMENT_ID}.tar.gz"

# Same exclusion intent as .dockerignore - the archive should contain exactly
# what the Docker build context would see, nothing more.
tar --exclude-from=.dockerignore \
    --exclude='.git' \
    --exclude='snapshots' \
    -czf "$ARCHIVE" .

HASH="$(sha256sum "$ARCHIVE" | cut -d' ' -f1)"
echo "$HASH  $(basename "$ARCHIVE")" > "$ARCHIVE.sha256"

echo "deployment_id: $DEPLOYMENT_ID"
echo "archive:       $ARCHIVE"
echo "sha256:        $HASH"
