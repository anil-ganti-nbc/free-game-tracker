# Amazon Luna Source Reconnaissance — Corrected

## 1. Re-establish the current product structure
Amazon Luna underwent major restructuring in mid-2026. The current official state is:
* **Luna Standard**: Active. The baseline Luna experience containing a rotating selection of games (including GameNight titles), included at no extra cost with an Amazon Prime membership.
* **Luna Premium**: Active. The paid expansion tier priced at $9.99/month offering the full library.
* **Amazon Prime Luna benefit**: Active. This is identically mapped to gaining access to "Luna Standard."
* **Prime Gaming claimable PC games**: Active. Separate from Luna cloud streaming, offering persistent PC game keys/downloads.
* **Luna+**: Renamed/Historical. Transitioned into the Luna Premium/Standard split. 
* **Ubisoft+**: Discontinued (as a Luna channel).
* **Jackbox Games**: Discontinued (as a Luna channel).
* **GOG library linking**: Discontinued (as part of BYOL shutdown).
* **EA library linking**: Discontinued.
* **Ubisoft Connect linking**: Discontinued.
* **Individual game purchases**: Discontinued.
* **Bring Your Own Library (BYOL)**: Discontinued.

## 2. Verify the 2026 third-party shutdown
* **Announcement date**: April 2026
* **Final access date**: June 10, 2026
* **Details**: Amazon officially discontinued support for third-party subscriptions directly through Luna (Ubisoft+, Jackbox), removed the ability to stream externally owned titles from GOG, EA, or Ubisoft, and disabled a-la-carte game purchases without providing refunds. Players must now use the official launchers of EA, GOG, and Ubisoft on local hardware to access those previously linked titles. The service pivoted entirely to the in-house Luna Standard and Luna Premium catalogs.

## 3. Inspect current Luna plan pages
* **Luna Standard**: Included with Prime. Exposes the rotating Prime selection. 
* **Luna Premium**: $9.99/mo upgrade.
* **GameNight**: Included within the Luna Standard (Prime) offering.
* **Page structure**: Heavy JavaScript rendering and GraphQL/JSON backends require specific headers/auth, making direct scraping without authentication difficult. Stable lists are primarily surfaced via announcements. No simple unauthenticated pagination over HTML exists.

## 4. Reassess Prime Gaming
* **Prime Luna access**: Cloud-streamed access under "Luna Standard."
* **Prime claimable PC games**: Keep-forever downloads via GOG/Epic/Amazon Games App.
Both are announced in the same monthly Prime Gaming blog post. 
**Recommendation**: Use a shared Amazon announcement discovery collector that splits into separate event normalizations to route PC claimables to `prime_gaming` and cloud additions to `amazon_luna`.

## 5. Reassess supported event types
* **Luna Standard additions**: reliably supported (via blog announcements)
* **Luna Premium additions**: reliably supported (via blog/PR announcements)
* **Prime-included Luna additions**: reliably supported (maps to Luna Standard)
* **Prime claimable PC games**: reliably supported (via blog announcements)
* **Catalog removals**: blocked (unlisted in standard blogs, UI-only)
* **Plan migrations**: historical only (migration from Luna+ to Standard/Premium occurred)
* **Third-party support removals**: historical only (completed June 2026)
* **Streaming-support additions**: historical only (BYOL ended)
* **Streaming-support removals**: historical only

## 6. Reassess canonical sources
`primegaming.blog` remains the canonical source for Prime benefits, which covers Luna Standard additions and PC claimables. For Luna Premium, the main *Amazon Games Newsroom (Amazon Games announcements)* serves as the canonical source. Neither exposes stable internal structural IDs.

## 7. Regional status
Currently restricted to 14 countries as of July 2026.
* **US**: Supported
* **UK**: Supported
* **Germany**: Supported
* **India**: Not Supported

## 8. Correct the architecture recommendation
Given the unified announcements on the blog but structurally different nature of the products, the tracking should use a shared discovery feed with split collectors:
```text
Amazon announcement discovery
├── Prime claimable events (prime_gaming)
├── Luna Standard catalog events (amazon_luna tier: standard)
├── Luna Premium catalog events (amazon_luna tier: premium)
└── historical third-party removal events (emit end-dates for prior tracker records)
```

AMAZON LUNA SOURCE RECONNAISSANCE — CORRECTED

Date: 2026-08-05
Verdict:
- Ready with conditions (Shared discovery feed parsing required; no live catalog verification)

Current plans:
- Luna Standard: Active (Included with Prime, rotating library)
- Luna Premium: Active ($9.99/month, expanded library)
- Prime Luna benefit: Active (Equates to Luna Standard)
- Luna+: Historical (Restructured into Standard/Premium)

Discontinued products:
- Ubisoft+: Discontinued June 10, 2026
- Jackbox: Discontinued June 10, 2026
- Individual purchases: Discontinued June 10, 2026
- Third-party stores: Discontinued June 10, 2026
- Bring Your Own Library: Discontinued June 10, 2026

Prime Gaming:
- Claimable PC games: Active, keep-forever downloads
- Luna cloud access: Active, streamed via Luna Standard
- Recommended collector split: Shared Amazon announcement discovery with separate event normalization for `prime_gaming` and `amazon_luna`.

Canonical sources:
- primegaming.blog (Luna Standard / PC Claimables)
- Amazon Games Newsroom / PR (Luna Premium additions)

Catalog verification:
- Blocked. Required HTTP headers and CAPTCHA hurdles prevent unauthenticated live catalog verification.

Departures:
- Blocked. Removals are minimally documented aside from transient "Leaving Soon" UI lists.

Regional availability:
- US: Supported
- UK: Supported
- Germany: Supported
- India: Not Supported

Reliably supported events:
- Luna Standard additions
- Luna Premium additions
- Prime claimable PC games additions

Partially supported events:
- None (Either definitively supported via PR/Blog, or completely undocumented).

Blocked events:
- Catalog removals
- Live continuous catalog syncing

Corrected collector architecture:
- Shared announcement discovery component that fetches from `primegaming.blog` and Amazon PR, followed by targeted parsers that route events to either the `prime_gaming` collector (for PC claimables) or the `amazon_luna` collector (for Standard/Premium cloud additions).

Previous claims withdrawn:
- Claims that Ubisoft+, Jackbox, GOG integration, EA integration, and Ubisoft Connect external ownership streaming remain active are fully withdrawn reflecting the June 2026 service shutdown.

Open questions:
- How will the shared discovery parser confidently separate a generic "Available on Luna" line into Standard versus Premium when Amazon sometimes omits specifics?
