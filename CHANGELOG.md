# Changelog

All notable changes to cascade-research will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Schema Migration System** (`storage/migrations.py`)
  - Version tracking via `schema_version` table
  - Forward and rollback migration support
  - Auto-migration on database initialization

- **Service Layer** (`services/`)
  - `KBService` for KB operations (CRUD, indexing)
  - `SearchService` for search with FTS5 query sanitization

- **Pre-commit Hooks** (`.pre-commit-config.yaml`)
  - Ruff linting and formatting
  - Basic file checks (trailing whitespace, YAML validation)
  - Pytest quick check on commit

- **Documentation**
  - `CONTRIBUTING.md` with development setup and PR workflow
  - `CHANGELOG.md` (this file)
  - `UPSTREAM_CHANGES.md` documenting fork differences

### Changed
- Fixed FTS5 query sanitization for hyphenated terms
- Fixed deprecation warnings (`datetime.utcnow()` → `datetime.now(timezone.utc)`)
- Improved test coverage (94 → 123 tests)

## [0.2.0] - 2025-02-21

### Added
- **Web UI** (`ui/`)
  - Streamlit-based interface with search, timeline, actors pages
  - Entry detail view with links and sources
  - Cached data layer for performance

- **REST API** (`server/api.py`)
  - FastAPI server with OpenAPI documentation
  - Full CRUD endpoints for entries
  - Search, timeline, tags, actors endpoints
  - CORS support for web frontends

- **Agent-Optimized CLIs**
  - `crk-read`: Read-only CLI for AI agents
  - `crk`: Full-access CLI for researchers
  - JSON output format with structured errors
  - Semantic exit codes

- **Claude Code Integration**
  - `.claude/skills/kb/skill.md` for Claude Code discoverability
  - MCP server for Model Context Protocol

### Changed
- Entry points consolidated: `crk`, `crk-read`, `crk-server`, `crk-ui`

## [0.1.0] - 2025-01-15

### Added
- **Multi-KB Architecture**
  - Support for multiple knowledge bases with different types
  - Events KB for timeline entries
  - Research KB for actors, organizations, themes

- **SQLite FTS5 Storage**
  - Full-text search with BM25 ranking
  - Tag and actor indexing
  - Link/relationship storage

- **Entry Models**
  - `EventEntry` for timeline events
  - `ResearchEntry` for research documents
  - YAML frontmatter parsing

- **GitHub OAuth**
  - Private repository access for collaborative research

- **Typer CLI**
  - Rich command-line interface (`cascade-research`)

## [0.0.1] - 2024-12-01

### Added
- Initial fork from joshylchen/zettelkasten
- Basic project structure
