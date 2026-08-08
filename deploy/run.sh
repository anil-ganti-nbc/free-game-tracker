#!/bin/sh
# Wrapper invoked by cron/systemd. Reads the currently-deployed image tag
# from a plain file so promoting a new image is a one-line file update, not
# an edit to the scheduler unit itself.
set -eu
cd "$(dirname "$0")/.."
export IMAGE_TAG
IMAGE_TAG="$(cat .deployed-tag)"
exec docker compose run --rm free-game-tracker run
