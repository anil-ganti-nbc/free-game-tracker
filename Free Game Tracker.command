#!/usr/bin/env bash
# Double-click to launch the Free Game Tracker dashboard locally, against
# the isolated local dev database. Delegates entirely to mac/dashboard —
# no logic lives here, and this never touches production.
cd "$(dirname "${BASH_SOURCE[0]}")"
exec mac/dashboard
