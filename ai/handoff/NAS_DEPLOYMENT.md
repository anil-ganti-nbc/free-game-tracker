# Deploying to a Synology NAS

Target confirmed: Synology, Container Manager not yet installed, CPU assumed x86_64
(**verify before trusting the images built this session** — see Step 0). Everything
built in this phase (`Dockerfile`, `docker-compose.yml`, backup/restore scripts,
external-scheduler assets) is host-agnostic — no Synology or cloud-specific paths are
baked into application source — so it should run on the NAS with no code changes,
only host-level configuration.

I have no network access to your NAS from this session. Everything below is a guide
for you (or a later agent given SSH access) to execute — I have not run any of it.

## Step 0 — Confirm the CPU architecture before trusting these images

DSM → Control Panel → Info Center, or SSH in and run `uname -m`.
- `x86_64` → the images already built and verified this session (`linux/amd64`) will
  run as-is.
- `aarch64`/`armv7*` → **stop**. Every image needs a `docker buildx build --platform
  linux/arm64 ...` rebuild and its own local verification pass before it's trustworthy
  on that hardware — do not assume an amd64-verified image behaves identically on ARM.

## Step 1 — Install Container Manager

Package Center → search "Container Manager" → Install. (Older DSM versions call this
package "Docker" — same thing, older UI.) This gives you both the GUI and the
underlying Docker Engine + Compose CLI over SSH.

## Step 2 — Enable SSH (Control Panel → Terminal & SNMP → Enable SSH service)

The Container Manager GUI can build/run individual containers, but for reproducing
this repo's `docker-compose.yml` exactly (named volumes, healthcheck, env
interpolation) SSH + the `docker compose` CLI is more reliable than reconstructing it
by hand in the GUI project import screen.

## Step 3 — Get the reviewed image onto the NAS

Do not build on the NAS itself if it's a low-power model — building pulls ~15
packages from PyPI and compiles nothing heavy, but a constrained NAS CPU will still be
much slower than a dev machine. Recommended path:

```bash
# On the dev machine, from the reviewed commit on cloud/free-game-production:
docker build --platform linux/amd64 -t free-game-tracker:<commit-sha> .
docker save free-game-tracker:<commit-sha> | gzip > free-game-tracker-<commit-sha>.tar.gz
```

Copy the `.tar.gz` to the NAS (File Station, SMB share, or `scp` once SSH is enabled),
then on the NAS:

```bash
gunzip -c free-game-tracker-<commit-sha>.tar.gz | docker load
```

This is also the immutable-artifact discipline the brief requires: the NAS receives a
built, tagged image, never a live source checkout or `git pull` + rebuild on the
device itself.

## Step 4 — Persistent storage

Create a Shared Folder (DSM UI, e.g. `docker-data`) and, under it, a
`free-game-tracker` subfolder — this becomes the bind-mount source instead of a Docker
named volume, since bind mounts to a Synology Shared Folder are what DSM's own
backup tooling (Hyper Backup) can see and snapshot. In `docker-compose.yml`, override
the volume:

```yaml
volumes:
  fgt_data:
    driver: local
    driver_opts:
      type: none
      device: /volume1/docker-data/free-game-tracker
      o: bind
```

(Put this override in a `docker-compose.nas.yml` you layer on top with `-f
docker-compose.yml -f docker-compose.nas.yml` — don't hand-edit the base file, keep
the override separate and reviewable like the existing staging overlay does.)

## Step 5 — Run it once, manually, before scheduling anything

```bash
IMAGE_TAG=<commit-sha> NEWSROOM_DISCORD_WEBHOOK_URL=<real-webhook> \
  docker compose -f docker-compose.yml -f docker-compose.nas.yml run --rm free-game-tracker run
```

Check `newsroom status`/`newsroom health` against the same volume before scheduling
anything automatic — same "cheap to destructive" ordering used throughout this
migration, just on new hardware.

## Step 6 — External scheduling: DSM Task Scheduler, not cron/systemd

Synology's own Control Panel → Task Scheduler → Create → Scheduled Task → User-defined
script covers exactly the "external scheduler → one-shot container → exit" model this
migration standardized on. The `deploy/run.sh` wrapper already built this session
works unmodified as that script's body — Task Scheduler just needs to invoke it:

```
/volume1/docker-data/free-game-tracker/deploy/run.sh
```

Set the recurrence to hourly, matching the existing Windows Task Scheduler cadence.
The `deploy/crontab.example` and `deploy/*.service.example`/`*.timer.example` files
built this session remain useful as a reference or for a non-Synology Linux host, but
DSM Task Scheduler is the natural choice here — don't install cron/systemd separately
just to match the docs literally.

## Step 7 — Private access: Tailscale

Check Package Center for an official "Tailscale" package first — Synology ships one
for many DSM/model combinations, which is simpler than running it as a container
(no shared network namespace tricks needed). If unavailable for this model, the
container path is a Tailscale sidecar joining the same Docker network — happy to help
set that up once Step 0 confirms the architecture and you've decided which path DSM
supports.

## Step 8 — Backup, the Synology way

`scripts/backup.py`/`scripts/restore.py` (already verified this session) still work
identically on the NAS — they're stdlib-only Python, no OS-specific behavior. Run
`docker compose run --rm free-game-tracker python scripts/backup.py` on whatever
schedule you want via Task Scheduler, writing into the same bind-mounted Shared
Folder. Because that folder is a real DSM Shared Folder (not an opaque Docker named
volume), Hyper Backup can also snapshot it directly as a second, independent backup
layer — closer to what the original NAS/HyperBackup architecture intended, without me
hard-coding any Synology path into the application itself.

## What I still can't verify without access

Everything above is written from what's true about the images/scripts already built
and verified in Docker Desktop this session, plus how Synology Container
Manager/Task Scheduler/Tailscale/Hyper Backup actually work. I have not run any of it
against your actual NAS. Before calling this production-ready on that hardware, redo
this migration's own verification checklist (build, non-root, identity/health,
persistence-across-recreation, backup/restore, scheduler firing, reboot recovery) on
the real device — a clean pass on Docker Desktop doesn't automatically transfer.
