# Stage 2.1: PlayStation Plus Collector with Context-Bound Date Parsing

Because there is no authenticated anonymous developer API explicitly tracking PSN catalog entries transparently, standard HTML scraping is mandatory. 

We aggressively proxy against the **PlayStation Blog RSS Feeds**.

## Official Sources Used
- `https://blog.playstation.com/category/ps-plus/feed/`: Canonical structured announcements for Essential monthly windows and Game Catalog drops locally synchronized with the exact timestamp.
- `https://blog.playstation.com/feed/`: The general PlayStation Blog feed, added after the Helldivers 2 incident (2026-08-12). The `ps-plus` category feed only ever contains the monthly roundup posts ("PlayStation Plus Game Catalog for August", etc.) — a same-day standalone article about one game (e.g. "Helldivers 2 joins PlayStation Plus Game Catalog today") is never one of that feed's own items, only a link inside a roundup's body. The general feed carries those standalone posts as their own items. Both feeds are polled and merged (fault-isolated per feed — one failing doesn't lose the other); see `SUBSCRIPTION_NOTIFICATION_INCIDENT_REPORT.md` for the full incident history.

### Standalone article detection
Roundup articles (title contains "monthly games" / "game catalog" / "games for") are parsed by `_extract_games_from_html` as before. Any other candidate from either feed is passed to `_detect_standalone_access_event`, which scans the article body — not just the headline — for a concrete claim that a specific game gained subscription access (e.g. "*Game* enters the PlayStation Plus Game Catalog", "*Game* will be available to PlayStation Plus Extra and Premium members"). Casual mentions (a requirement, a discount, an unrelated link) do not match and produce no event. This exists because a first-party article can be primarily about an update or a launch while still containing a genuine access-change announcement — the Helldivers 2 "Devoid of Liberty" article is exactly that shape.

A standalone article and a same-day roundup can both describe the same game (as happened in the Helldivers 2 case). `fetch_events()` deduplicates by content (event type, service, title, tiers, availability date) — not by URL — so this doesn't produce two events for one real-world change.

## Date Rules (Stage 2.1)
Context-bound parsing avoids date leakage across unrelated sections by enforcing a strict hierarchy.
Dates are assigned dynamically according to the smallest valid structural section in this order:
1. **Game specific**: E.g., Date strings inside the preceding `<p>` or `<li>` enclosing the game title `<strong>` tag.
2. **Section heading**: E.g., Date explicitly listed inside `<h2>` / `<h3>`. 
3. **Article-Level**: Global date matching at the beginning of the blog string.

**Supported relative/explicit strings:**
- `Available from [Month] [Day]`
- `Available from [Month] [Day] until [Month] [Day]`
- `Claim by [Month] [Day]`
- `Joining the catalog on [Month] [Day]`
- `Available today` (mapped precisely to UTC mapped `pubDate`)
- `Available next Tuesday` (resolved deterministically assuming `pubDate` anchor).

Null bounding logic gracefully catches unresolvable edge phrases and records explicit warning fields preventing destructive metadata assumptions! 

### Year Inference Rules
Missing years are intelligently resolved using explicitly bounded rules matching `pubDate`:
- Defaults to `pubDate.year`.
- **December to January wrapping**: For `from December until January` ranges, end dates dynamically receive `pubDate.year + 1`. 
- **Late year overlap**: If the parsed month is earlier than the `pubDate.month` and the `pubDate` falls into Q4 (month >= 11), it receives `pubDate.year + 1`.

### Timezone handling
Datetimes are assigned UTC strictly. If availability has no time, it defaults directly to Midnight `00:00:00` against UTC bounds deterministically.

## Regional Handling
Regions uniquely control Deluxes capabilities dynamically against PlayStation streaming restrictions natively. Uses string boundary tags matching `Deluxe`.
**Validation**: Fully validated against captured US bounds for Premium and Deluxe differences fixture-validated safely.

## Tier Mapping
Extracted cleanly checking RSS DOM boundaries dynamically isolating `<strong>` and semantic header tags identifying distinct tiers logically parsing:
- `PlayStation Plus Extra and Premium` => `extra`, `premium`
- `PlayStation Plus Premium` => `premium` (and tracks `classics` natively inside metadata properties).
- Monthly Games bounds identically evaluating `essential`.

## Confidence Rules
Returns `95` explicitly if `<strong>Title | Platform</strong>` successfully maps and tags cleanly. A `60` floor defaults aggressively filtering potential PR paragraphs mapping accidentally!

## Notifications
PlayStation Plus events (`Category.SUBSCRIPTION`) have their own Discord delivery path — `newsroom.notify.build_subscription_payload` / `notify_new_subscription_events` — separate from the giveaway path (`build_discord_payload` / `notify_new_giveaways`, gated to `Category.GAME_PROMOTION`). This distinction is deliberate and permanent, not a workaround: subscription access is never ownership, and the subscription embed says so explicitly (Service / Event / Tier / Availability / "Subscription access (not ownership)"), with no price field and no "free" language.

Until 2026-08-12, `Category.SUBSCRIPTION` events had no Discord path at all — they were correctly discovered, classified, and stored, but silently never posted, for every PlayStation Plus, Xbox Game Pass, and GeForce Now event since these sources existed. The Helldivers 2 "joins PS Plus Game Catalog" incident is what surfaced this. Full history: `SUBSCRIPTION_NOTIFICATION_INCIDENT_REPORT.md`. A coverage test (`newsroom/tests/test_category_coverage.py`) now fails CI if a registered source can emit a category with no corresponding entry in `notify.CATEGORY_NOTIFIERS`, so this class of gap can't recur silently for a future category.

## Limitations
- **Trials**: Explicit tracking blocked.
- **Departures**: Blocked. PlayStation explicitly removed `Leaving Soon` sections from canonical RSS streams.
- **Dashboard UI**: Blocked temporarily maintaining generic tables explicitly.
