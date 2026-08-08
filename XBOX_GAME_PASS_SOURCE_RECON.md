XBOX GAME PASS SOURCE RECONNAISSANCE

Date: 2026-08-05
Verdict:
- Ready with conditions (requires mapping plans and handling unofficial catalog endpoints)

Current official plans:
- **Xbox Game Pass Ultimate**: Currently active. The top-tier including Day-One games, EA Play, Cloud, PC, and Console. Display name: "Ultimate".
- **Xbox Game Pass Premium**: Currently active. Formerly "Standard". Includes Console and PC but no Day-One XBOX-published releases. Display name: "Premium".
- **Xbox Game Pass Essential**: Currently active. Formerly "Core". Includes entry-level curated games, mostly Console and Cloud. Display name: "Essential".
- **PC Game Pass**: Currently active. PC-only library with Day-One releases and EA Play. Display name: "PC only" or "PC Game Pass".
- **Xbox Game Pass Core**: Renamed (now Essential).
- **Xbox Game Pass Standard**: Renamed (now Premium).
- **Xbox Game Pass for Console**: Historical (replaced by Standard, which became Premium).

Canonical announcement source:
- Source name: Xbox Wire
- URL or endpoint: https://news.xbox.com/en-us/
- Owner: Microsoft
- Region: US (Global proxy, but subjective to translation/redirects)
- Authentication required: None
- Content type: HTML / RSS
- Announcement or live catalog: Announcement 
- Events exposed: Additions, partial departures, EA Play inclusions, Day-one announcements
- Reliability: High for initial marketing, but dates or plans can sometimes be inaccurate compared to the live catalog.

Catalog-verification source:
- Source name: Xbox Display Catalog API & Game Pass catalog endpoints
- URL or endpoint: https://catalog.gamepass.com/sigls/v2?id={list_id}&language=en-us&market=US and https://displaycatalog.mp.microsoft.com/v7.0/products (unofficial usage)
- Owner: Microsoft
- Content type: JSON
- Announcement or live catalog: Live Catalog
- Reliability: High (direct truth from store servers), but endpoints are undocumented.

Departure source:
- Source name: Xbox Wire "Leaving Soon" sections and Xbox Store "Leaving Soon" collections.
- Reliable unauthenticated official source: There is no dedicated public API for departures. It depends on scraping Xbox Wire prose or tracking store ID rotations. It is recommended to use community mappings or the `sigls/v2` list ID for leaving soon.

Regional sources:
- Regions: US, GB, IN, etc.
- Web articles generally redirect or might be delayed.
- The `market=` parameter in the Display Catalog API (e.g., `market=IN`) allows resolving regional catalog differences effectively. Do not assume full global parity based on Xbox Wire US.

Structured endpoints:
- List of Game IDs: `https://catalog.gamepass.com/sigls/v2?id={list_id}&language=en-us&market=US`
- Game metadata: `https://displaycatalog.mp.microsoft.com/v7.0/products?bigIds={CommaSeparatedIds}&market=US`

Authentication or blocking:
- Xbox Wire: No auth required.
- Catalog API: No auth required, but subject to rate-limiting and undocumented changes.

Events reliably supported:
- Additions (Xbox Wire & structured endpoints)
- Departures (Xbox Wire announcements, visual checks)

Events partially supported:
- Platform specifics (Handheld vs PC vs Console varies in formatting).
- Plan eligibility (Relies on matching recent rebranding).
- Day-one (Explicitly called out in Xbox Wire text, but not always definitively typed in API).

Events blocked:
- Full programmatic historical verification without a prior database (no historical API).

Plan extraction:
- Extracted via text parsing from Xbox Wire headings/bullet points (e.g., "Game Pass Ultimate, Game Pass Premium, PC Game Pass"). Needs robust alias mapping due to historical plan names.

Platform extraction:
- Listed in parentheses in Xbox Wire (e.g., `(Cloud, Xbox Series X|S, Handheld, and PC)`).

Date extraction:
- Attached to titles or text (e.g., `– August 4`). Needs cautious parsing as headings ("Available Today") or mixed article dates can bleed.

Day-one extraction:
- Usually written as `Available on day one with Xbox Game Pass!`. It must remain unknown if not explicitly found in text.

Regional risks:
- Xbox Wire US only implies US availability. Cloud games and specific titles often have differing licensing in India or Europe. Recommended to verify with the `market` parameter.

Identity risks:
- PC and Console editions might share a store page or have separate `bigId`s.
- EA Play vs standard Game Pass ID collisions.
- Duplicate mentions across "Cloud" and "PC" headings.
- Re-announcements or delayed launches might trigger duplicates if using article-based IDs.

Recommended collector architecture:
- Monitor Xbox Wire RSS for event triggers. 
- Do NOT solely rely on text scraping formatting. Extract title names, cross-reference them via search or fuzzy-match, and pull the canonical status from `displaycatalog.mp.microsoft.com` to resolve plan, platforms, and true ID.

Recommended fixture set:
- Xbox Wire HTML extracts (mocked "Coming Soon" sections).
- `catalog.gamepass.com/sigls/v2` list responses.
- `displaycatalog.mp.microsoft.com` single product JSON.
(Saved in temporary `research.json` and not committed).

Recommended live-validation procedure:
- Dry-run parsing over the last 3 Xbox Wire posts. 
- Compare extracted additions with current `sigls/v2` catalog lists.

Open questions:
- Are there stable list UUIDs for "Leaving Soon" that will not rotate away?
- Will EA Play remain bundled into Premium/Ultimate indefinitely, or does it require a distinct subscription attribute?
