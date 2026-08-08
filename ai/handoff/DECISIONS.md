# Decisions — Free Game Tracker cloud migration

1. **Live Desktop folder, not the stale `unified/free-game-tracker` snapshot, is the
   authoritative source.** A prior portability attempt (by a different agent, "Grok") had
   built a Dockerfile/compose/entrypoint/runtime_bridge in a separate, ~5-day-stale copy
   that was never verified against a real Docker build. Adapted as a template/recipe, not
   copied wholesale — the live tree has grown substantially since (Amazon/Luna, PS Plus,
   Xbox Game Pass, GeForce Now sources didn't exist in the stale snapshot).

2. **`release_channel` defaults to `"experimental"`, never `"production"`.** The prior
   template hard-coded `RELEASE_CHANNEL = "production"` in `runtime_bridge.py`. That would
   have let a freshly built, never-tested candidate image self-report as production the
   moment it started — a truthfulness violation per the brief. Made it configurable via
   `NEWSROOM_RELEASE_CHANNEL`/`settings.release_channel`, defaulting to the least-trusted
   channel. Production compose sets it explicitly once promotion is authorized.

3. **`identity`/`health` are new, additive CLI commands, not replacements.** Existing
   `version`/`run`/`status`/etc. behavior and output format are untouched, so nothing that
   currently parses `newsroom version`'s plain-text output breaks.

4. **Backup/restore use sqlite3's online backup API, not a raw file copy.** Handles a
   WAL-mode write in progress correctly; avoids imposing any journal-mode change on the
   application (none was made).

5. **No dashboard (`serve`) capability in the production image by default.** The `gui`
   extra isn't installed; the one-shot cron job never needs it, and the brief prefers no
   public exposure by default. `serve` still routes correctly through the entrypoint and
   fails with the existing friendly error message if invoked without the extra — this is
   pre-existing behavior, not new.

6. **Did not provision any cloud host or push any git history.** Per the brief's staged
   gates and the explicit "no push yet" instruction — this phase is local verification
   only. Cloud host selection needs its own approval (provider, size, cost) before the
   remaining acceptance-gate items (external schedule over real time, reboot recovery,
   real-network notification test, Tailscale) can be completed.
