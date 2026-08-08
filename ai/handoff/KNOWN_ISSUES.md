# Known issues — Free Game Tracker cloud migration

## Found and fixed this phase

**Portability defect: alembic path resolution broke under a real `pip install`.**
`PROJECT_ROOT = Path(__file__).resolve().parent.parent` assumed the package always runs
from an editable/source checkout, where `newsroom/` sits directly under the files
`alembic.ini`/`alembic/`. A non-editable `pip install .` (what the container does) moves
the *package* into `site-packages` while `alembic.ini`/`alembic/` — which are project
files, not part of the package — stay wherever they were copied. `init_db()` then looked
for `alembic/env.py` inside `site-packages` and failed. Fixed with a new
`settings.alembic_home` override (default unchanged, so native/Windows/dev behavior is
identical) pointed at `/app` via a Dockerfile env var. Classified as a packaging/portability
defect per the brief's framework, not a schema or migration behavior change — no
migrations were added, removed, or altered.

## Pre-existing, documented, intentionally not touched

- Two overlapping Windows Task Scheduler registration mechanisms exist
  (`Install-HourlyTask.ps1` vs. the older `scripts/register-task.ps1` +
  `scripts/run-newsroom.ps1`) — likely one is dead. Not resolved here; out of scope for a
  portability pass, and Windows-side scheduling is untouched regardless since the container
  path uses its own external-scheduler assets under `deploy/`.
- `newsroom_intelligence/` — a dead first-attempt scaffold folder, explicitly flagged
  removable in `HANDOFF.md`. Left in place; not part of the container image (excluded via
  `.dockerignore`, not copied by the `Dockerfile`).
- GamerPower source is behind Cloudflare and can be unreachable from some restricted
  network environments. Not reproduced in this environment (dry run succeeded), but
  documented as a risk for whichever cloud host is eventually chosen.
- No clean shutdown path historically documented for the dev `uvicorn` dashboard process
  (manual `taskkill` in prior sessions). Not relevant to the one-shot `run` container path;
  would matter only if `serve` is ever deployed long-running, which is not part of this
  phase.
- README/HANDOFF understate the actual feature surface (Amazon/Luna, PlayStation Plus,
  Xbox Game Pass, GeForce Now sources exist and are tested but undocumented in the top-level
  README). Doc-drift, not a migration concern; not corrected here.

## Explicitly deferred (needs a cloud host, not yet approved)

- External scheduler actually firing over real elapsed time (asset created and its syntax
  is standard cron/systemd; not yet observed running on a host).
- Host reboot / container-crash recovery.
- Notification delivery from the real target cloud network (this phase deliberately never
  exercised the real Discord webhook).
- Tailscale / private-access model.
