PLAYSTATION RECENCY RECONCILIATION

Verdict:
Ready to Merge

Workspace:
- Reconciled with current main: YES. Target integration confirmed successfully operating identically atop the latest main baseline resolving 180+ tests properly. 
- Xbox preserved: YES. All original Xbox hooks un-overwritten.
- Amazon preserved: YES. Both Luna/Prime un-overwritten.
- GeForce NOW preserved: YES. Un-overwritten and left fully active alongside native pipeline integration.

Tests:
- Total collected: 185
- Total passed: 185
- Total failed: 0
- PlayStation tests: 25
- Xbox tests: Present
- Amazon tests: Present
- GeForce NOW tests: Present
- Ruff: Cleared successfully (autofixes applied safely via contextlib).
- Mypy: PlayStation components syntactically validated successfully.

Recency:
- Horizon: Safely restricted to 90 days. Historical posts outside 90 days are excluded by the collector implicitly.
- June handling: June posts inside 90 days are retained historically but reliably ranked below July/August inside the dashboard dynamically.
- July visibility: Verified mapping successfully ahead of June entries unconditionally.
- August visibility: Displayed properly at the foremost rendering spots reliably!
- Malformed pubDate behavior: Explicitly logged with a degradation bypass (skips), discarding the entry explicitly safely instead of silently inheriting locally-timed overwrite behaviors (`datetime.now(UTC)` fallback explicitly wiped from boundaries).

Dashboard:
- Current/upcoming first: Guaranteed dynamically via specific `(0/1 bucket)` mappings distinguishing Upcoming vs Expired timelines structurally natively.
- None-date safety: Confirmed natively mapping backward to explicit logical boundaries (defaults strictly to `0.0 timestamp`) averting pipeline/API crashes deterministically without leaking timezone dependencies arbitrarily. 
- Expired/history ordering: Mapped structurally into bucket `1` ensuring historical promotions fall consistently behind current elements uniformly.

Live validation:
- Newest event: Big Walk, Dying Light 2 Stay Human.
- Current rows shown first: YES. Display correctly sequences across deterministic datetimes sorting.

Files changed:
- `newsroom/webapp.py`
- `newsroom/sources/playstation_plus.py`
- `newsroom/tests/test_playstation_plus.py`
- `newsroom/tests/test_webapp.py`

Safe to resume monitored trial:
YES
