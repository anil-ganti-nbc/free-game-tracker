#!/bin/sh
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
