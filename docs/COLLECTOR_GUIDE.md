# Newsroom Collector Guide

This document defines the canonical architecture, lifecycle, and review pipeline for all collectors within the Free Game Tracker / Newsroom system. All future and active collectors MUST strictly adhere to this specification.

Reference implementations: **PlayStation Plus** and **Xbox Game Pass**.

## Canonical Collector Lifecycle

```text
Reconnaissance
→ Design
→ Implementation
→ Hostile Review
→ Reconciliation
→ Live Validation
→ Freeze Readiness
→ Frozen
```

## 1. Discovery
The discovery phase dictates how a collector identifies new information.
- **Authoritative Sources**: Collectors must rely exclusively on official primary sources (e.g., PlayStation Blog, Xbox Wire).
- **Undocumented APIs**: Undocumented APIs must be optional enrichment only (e.g., enriching Xbox Game Pass entries with store images), never the sole canonical mechanism for discovery.
- **Network Failures**: Network failures must not silently return an empty successful result. Failures must clearly bubble up as errors.

## 2. Normalization
- **Scrubbing & Title Normalization**: Remove publisher-specific marketing fluff and non-functional characters to ensure reliable identity matching.
- **Context-Bound Dates**: Date parsing must be context-bound to paragraph/section headers. 
- **Timezones**: Relative dates must use a real timezone via standard libraries (e.g., Python's `ZoneInfo`), not fixed UTC offsets.
- **Publication vs. Release Dates**: Publication dates must not be treated as release dates unless explicit source wording fully justifies it.
- **Layout Outcomes**: A recognized source layout that is expected to contain applicable events but yields zero events must be treated as degraded or failed unless the source is demonstrably a valid empty state. “No relevant post,” “valid empty announcement,” “unrecognized layout,” and “parser failure” must remain distinct outcomes.

## 3. Event Model
Collectors do not write direct state; they produce **Events**.
- **No Direct Database Writes**: Collectors must not write directly to the database. They only yield event payloads for the persistence pipeline to ingest.
- **Legacy Keys**: Legacy event keys must remain unchanged to ensure downstream compatibility.
- **Event Taxonomy**: `CATALOG_ADDITION`, `CATALOG_REMOVAL`, `CLAIMABLE_GAME`, `TRIAL_ADDED`, `DLC_ADDED`, `PERK_ADDED`, `STREAMING_SUPPORT_ADDED`, `STREAMING_SUPPORT_REMOVED`, `AVAILABILITY_CHANGED`, `DATE_CHANGED`, `TIER_CHANGED`, `RELEASE_DELAYED`

## 4. Identity Generation
Establishing canonical game identity across disparate stores is critical.
- **Stable Distinctions**: Event identity must include stable per-game distinctions. Identity must not depend solely on an announcement URL. Stable per-game identity must include title, edition, App ID, product ID, storefront, tier, platform, date, or another source-supported distinguishing field as appropriate to the service.
- **Collision Avoidance**: Multiple games sharing one article URL (e.g., in a monthly PlayStation Plus blog post) must not collide. Titles with similar names must have strictly distinct identities.

## 5. Ownership Models
Clear distinction must be maintained between different types of entitlements.
- **Subscription Access**: Subscription access (e.g., Xbox Game Pass) must never be described as permanent ownership.
- **Streaming Requirements**: GeForce NOW-style streaming support requires external ownership and must be modeled as such, not as an innate bundled entitlement.

## 6. Access Models
- **Tiering**: Track specific tiers meticulously (e.g., PS Plus Essential vs Premium).

## 7. Confidence Scoring
All discovered insights must attach a confidence score from 0 to 100, with explicit reasons.

## 8. Health Reporting
- **Collector Independence**: One collector or normalizer failing must not suppress unrelated collectors.
- **Isolated Target Runs**: Isolated source runs must not mark omitted collectors as expired.
- **Known Limitations**: Known limitations must be documented explicitly, specifically, and honestly.

## 9. Notifications
- **No Direct Notifications**: Collectors must not send notifications directly. They emit events that the isolated notification layer handles.
- **Tier Isolation**: Suppress subscription additions from legacy free-to-keep giveaway alerts.

## 10. Regional Handling
- **Verified Source Context**: Region must come from verified source context and must not default to `global`. 
- **Parameterization**: Collectors must fetch and validate region-specific data (e.g., Xbox Game Pass catalog differences).

## 11. Persistence
- **Write Path**: Persistence is handled downstream. Events traversing to a durable store act as an UPSERT operation.
- **Conflict Resolution**: Conflicting assertions must be resolved using source authority, explicit correction or update semantics, and field-level confidence. A newer observation must not overwrite an earlier official value merely because it was observed later. Provenance must be retained.

## 12. Testing Requirements
- **Test Types**: Tests decorated as fixtures do not count as executed test coverage. Placeholder tests and assertion-free tests are completely prohibited.
- **Verification**: Test counts must be verified by actually running `pytest`.
- **Linting & Typing**: `ruff` and `mypy` must pass strictly.
- **Live Validation Rules**: Live validation must use the real parser against the real source context, not a mocked parser. HTTP 200 alone is not live validation. Live validation requires the real discovery parser, real normalization path, and real source structure to produce or correctly classify events without mocked discovery.

## 13. Fixture Requirements
- **Real Structure**: Fixtures must reflect real source structure (e.g., actual HTML/XML RSS dumps) rather than simplified mock dictionaries.

## 14. Hostile Review Checklist
Hostile review is mandatory before enabling a new collector by default.
- [ ] Are dates purely derived from context, or are they brittle Regex assumptions?
- [ ] Is timezone handling utilizing `ZoneInfo` accurately?
- [ ] Does a subscription event leak into a core giveaway notification channel?
- [ ] Is identity stable for multiple games on a single URL?
- [ ] Were branch/worktree reconciliations executed in a way that preserves other agents’ changes? No agent may restore a green baseline by deleting, unregistering, or bypassing another accepted collector. Missing or broken cross-agent work must be reconciled against current main rather than amputated.

## 15. Freeze Readiness Checklist
Freeze readiness is mandatory before enabling a collector by default.
- [ ] Final validation must run from the reconciled main workspace.
- [ ] Explicit ownership and access models fully aligned with the global architectural taxonomy.
- [ ] Test suite executes completely correctly as reported by running `pytest`.

## Collector Status Levels
- **PRODUCTION_READY**: The collector has undergone live-source validation and is actively enabled.
- **PRODUCTION_READY_WITH_CONDITIONS**: The collector is active but has specific explicitly documented known limitations.
- **FIXTURE_VALIDATED_DISABLED**: The collector is disabled in production but passes its fixture-based test suite ("Production Ready" claims missing live validation fall here).
- **BLOCKED**: The collector cannot operate due to upstream changes or missing logic.
- **FROZEN**: The collector is feature-frozen after reconciliation, live validation, hostile review, and freeze-readiness approval. It may receive bug fixes, source-breakage repairs, security fixes, reliability fixes, and required test maintenance, but no new capabilities without reopening the lifecycle.
