# Stage 2.1: PlayStation Plus Collector with Context-Bound Date Parsing

Because there is no authenticated anonymous developer API explicitly tracking PSN catalog entries transparently, standard HTML scraping is mandatory. 

We aggressively proxy against the **PlayStation Blog RSS Feeds**.

## Official Sources Used
- `https://blog.playstation.com/category/ps-plus/feed/`: Canonical structured announcements for Essential monthly windows and Game Catalog drops locally synchronized with the exact timestamp.

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

## Limitations
- **Trials**: Explicit tracking blocked.
- **Departures**: Blocked. PlayStation explicitly removed `Leaving Soon` sections from canonical RSS streams.
- **Dashboard UI**: Blocked temporarily maintaining generic tables explicitly.
- **Notifications**: Category identically bypassed suppressing misleading "Free Giveaway" messages to Discord globally via `Category.GAME_PROMOTION` boundary checks. 
