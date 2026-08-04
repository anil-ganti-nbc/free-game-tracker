#!/bin/sh
# External-scheduler entry (Linux). Replaces scripts/run-newsroom.ps1.
set -eu
cd "$(dirname "$0")/.."
mkdir -p logs data/reports
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) starting newsroom run" >> logs/run-$(date -u +%Y%m%d).log
newsroom run >> logs/run-$(date -u +%Y%m%d).log 2>&1
ec=$?
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) finished (exit $ec)" >> logs/run-$(date -u +%Y%m%d).log
exit $ec
