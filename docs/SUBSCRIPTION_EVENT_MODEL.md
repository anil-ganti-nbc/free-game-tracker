# Subscription Event Model (Stage 1)

## Event Taxonomy
To gracefully support subscription events natively on the existing `NewsEvent` schemas without polluting legacy models, we have expanded `Category` to include `SUBSCRIPTION`.

We have also added new Enum structures:
- `EventType`: Distinguishes additions, removals, trial starts, and tiered perks securely.
- `AccessModel`: Maps definitions matching subscription catalogs strictly.
- `OwnershipModel`: Defines exactly if models are permanently assigned to accounts or strictly bounded to service windows.

### Distinction: Source vs Service
`Source` identifies the mechanical collector providing the data (e.g., `gamerpower`).
`Service` identifies the explicit consumer subscription label (e.g., `PlayStation Plus`, `Xbox Game Pass`). They are completely separable natively.

### Distinction: Event Type vs Access Model
`EventType` tracks the transactional *verbs* of the event (e.g. `CATALOG_ADDITION`), while `AccessModel` describes the *noun* of accessibility (e.g., `SUBSCRIPTION_CATALOG`). 

## Event Identity Rules
A critical requirement is deduplication natively relying perfectly identically on string properties mapped tightly. 

### Legacy Behavior
Historical models utilizing `Category.GAME_PROMOTION` unconditionally return `f"{source.value}:{url}"`. This ensures that existing tracking stays 100% resilient generating zero duplications globally.

### Subscription Behavior
Because subscriptions map identical URLs across variable tiers internally seamlessly, `Category.SUBSCRIPTION` triggers deterministic variants dynamically. It parses:
- Services
- Normalized (alphabetical) tier strings
- Regions and platforms
- Start/end bounding windows natively checking Unix stamps.

A cryptographic SHA-256 string is generated preventing unbounded key lengths, generating identities strictly resolving as:
`source:url:event_type:service:digest`

This separates tier collisions securely without risking JSON collisions. 

## Legacy Compatibility
The schema additions default gracefully securely to `None`. No legacy sensors require rewrites. All database operations perfectly round-trip the unpopulated arrays keeping JSON lists empty by default natively protecting existing records strictly.
