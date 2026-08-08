# Newsroom Intelligence Platform

An operating system for news discovery. Automated detection of facts worth writing about.

## Core Mission

**Discover news before humans do.**

The system answers one question: *"Is there something worth writing about?"*

Not article generation. Not summarization. Just facts + evidence + detection.

## Architecture Overview

```
Source → Normalize → Validate → Store → Compare → Score → Notify
```

Every step is independent and modular.

### Key Components

#### 1. NewsEvent
The central data model. Represents a single piece of potentially newsworthy information.

Every source converts its raw data into NewsEvents:
- Game promotions → NewsEvent
- Semiconductor leaks → NewsEvent  
- Kernel commits → NewsEvent
- Regulatory filings → NewsEvent

The pipeline doesn't care about the source type.

#### 2. SourcePlugin
Abstract base class. Every news source implements this interface.

```python
class SourcePlugin:
    def fetch() -> list[NewsEvent]: ...
    def validate(event: NewsEvent) -> bool: ...
```

No coupling. No knowledge of:
- Database
- Notifications
- Scoring
- Other sources

#### 3. Pipeline
Transforms NewsEvents through:
- **Fetch**: Get raw data from sources
- **Normalize**: Convert to NewsEvent
- **Validate**: Ensure data quality
- **Store**: Persist to database
- **Compare**: Detect changes vs. historical data
- **Score**: Assign editorial impact
- **Notify**: Alert editors

## Project Structure

```
newsroom_intelligence/
├── src/newsroom_intelligence/
│   ├── __init__.py           # Package entry
│   ├── models.py             # NewsEvent, Category, PromotionType
│   ├── source.py             # SourcePlugin base class
│   ├── config.py             # Settings management
│   ├── logging.py            # Structured logging
│   ├── cli.py                # Command-line interface
│   ├── sources/              # Plugin implementations (future)
│   ├── pipeline/             # Pipeline stages (future)
│   ├── storage/              # Database layer (future)
│   ├── scoring/              # Impact scoring (future)
│   └── notify/               # Notification layer (future)
├── tests/
│   ├── test_models.py
│   ├── test_source.py
│   └── conftest.py
├── config/                   # Configuration files
├── docs/                     # Documentation
├── pyproject.toml            # Dependencies
├── .env.example              # Configuration template
└── .gitignore
```

## Tech Stack

- **Python 3.12+** - Type-safe, modern
- **Pydantic** - Data validation
- **SQLAlchemy** - ORM (extensible to PostgreSQL)
- **Typer** - CLI
- **httpx** - HTTP client
- **BeautifulSoup** - HTML parsing
- **pytest** - Testing
- **ruff** - Linting
- **mypy** - Type checking
- **loguru** - Structured logging

## Development

### Setup

```bash
cd newsroom_intelligence
uv sync
source venv/bin/activate
```

### Run Tests

```bash
pytest tests/ -v
```

### Type Checking

```bash
mypy src/
```

### Linting

```bash
ruff check src/
```

## Phases of Implementation

### Phase 0: Foundation ✓
- [x] Project structure
- [x] Core data models (NewsEvent)
- [x] SourcePlugin abstraction
- [x] Configuration management
- [x] Logging setup
- [x] Basic CLI skeleton
- [x] Test structure

### Phase 1: Core Abstractions (Next)
- [ ] NewsEvent validation
- [ ] SourcePlugin utilities
- [ ] Change detection types
- [ ] Scoring framework
- [ ] Integration tests

### Phase 2: First Source Plugin
- [ ] Epic Games Store source
- [ ] HTML parsing
- [ ] Error handling
- [ ] Rate limiting

### Phase 3: Additional Sources
- [ ] Steam source
- [ ] GOG source
- [ ] Cross-source deduplication

### Phase 4: Change Detection
- [ ] Historical comparison
- [ ] Delta detection
- [ ] Expiration tracking

### Phase 5: Storage Layer
- [ ] SQLAlchemy models
- [ ] SQLite integration
- [ ] Migration system

### Phase 6: Scoring & Reporting
- [ ] Editorial impact scoring
- [ ] Markdown/JSON reports
- [ ] Discord notifications

### Phase 7: Production Ready
- [ ] Docker support
- [ ] GitHub Actions CI
- [ ] Deployment docs
- [ ] Comprehensive tests

## Design Philosophy

1. **Modularity**: Single responsibility per component
2. **Type Safety**: Full type hints, mypy clean
3. **Extensibility**: New sources ≠ code changes
4. **Resilience**: Graceful failures, retry logic
5. **Clarity**: Comments > clever code
6. **Testing**: Every public interface tested
7. **Logging**: Structured, searchable logs
8. **Documentation**: Code is documentation

## Future Directions

Once the game promotion monitor is stable:

- **Semiconductor Leaks**: Parse PCI ID databases, benchmark leaks
- **Kernel Commits**: Monitor Linux, Windows, macOS commits
- **Regulatory Filings**: SEC, FTC, international regulators
- **Benchmark Databases**: Geekbench, 3DMark, GFXBench
- **Firmware Releases**: BIOS, GPU drivers, SSD controllers
- **Retailer Listings**: Product pages, stock changes, pricing
- **Official Announcements**: Press releases, earnings calls

## Philosophy

Build for three years ahead. Assume this code will be maintained longer than it takes to write.

Prefer boring, readable, maintainable code. Do not optimize prematurely.

Test everything. Document everything.

Make it easy for someone else (or future you) to add a new source. If adding a new source is hard, the architecture failed.

---

**Status**: Phase 0 Complete — Awaiting Approval
