#!/bin/sh
# Container entrypoint. External scheduler invokes this via
# `docker compose run --rm free-game-tracker run` (or another subcommand).
# No in-process scheduling, no browser launch, no GUI.
set -eu
cd /app
mkdir -p /app/data/reports 2>/dev/null || true
if [ "$#" -eq 0 ]; then
  exec newsroom run
fi
case "$1" in
  newsroom) shift; exec newsroom "$@" ;;
  version|identity|health|run|status|init-db|fetch|serve)
    exec newsroom "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
