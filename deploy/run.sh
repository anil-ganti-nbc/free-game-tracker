#!/bin/sh
# Wrapper invoked by cron/systemd. Reads the currently-deployed deployment
# identifier from a plain file so promoting a new image is a one-line file
# update, not an edit to the scheduler unit itself. Not a git commit SHA -
# GitHub is not in use for this project yet; see ai/handoff/DECISIONS.md.
set -eu
cd "$(dirname "$0")/.."
export IMAGE_TAG
IMAGE_TAG="$(cat .deployed-id)"
exec docker compose run --rm free-game-tracker run
