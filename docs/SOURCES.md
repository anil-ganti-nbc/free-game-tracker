# Sources Strategy
The application explicitly avoids dirty scraping loops relying dynamically on authoritative structured streams actively preserving confidence gracefully.

## Architecture
All parsers inherit `newsroom/sources/_http.py` generating standard deterministic `httpx` timeouts. 
If an official source goes offline, it returns `SourceError` gracefully cleanly failing without crashing sibling streams.

## Active Sources
1. **Epic Games** (`epic`): GQL canonical.
2. **GOG** (`gog`): Public structured API.
3. **Steam** (`steam`, `steam_breakouts`, `steam_deals`): Built-in internal discovery streams natively handling scraping natively reliably via structured headers.
4. **GamerPower** (`gamerpower`): Aggregator API.
5. **PlayStation Plus** (`playstation_plus`): Official Canonical RSS Feed endpoints structurally isolating raw HTML natively parsed against strict schema Regex. 
