# Upstream Changes

This document tracks how cascade-research differs from the upstream [joshylchen/zettelkasten](https://github.com/joshylchen/zettelkasten) project.

## Overview

cascade-research is a fork designed for multi-KB research workflows with AI agent integration. The core zettelkasten note-taking functionality is preserved, but significantly extended for investigative journalism use cases.

## Major Architectural Changes

### 1. Multi-KB Support

**Upstream:** Single knowledge base
**cascade-research:** Multiple knowledge bases with different types

```yaml
# cascade-research config supports multiple KBs
knowledge_bases:
  - name: timeline
    path: /path/to/timeline
    type: events      # Timeline-specific schema
  - name: research-kb
    path: /path/to/research
    type: research    # Flexible research documents
```

**Files changed:**
- `cascade_research/config.py` — Added `KBConfig`, `KBType`, multi-KB loading
- `cascade_research/storage/repository.py` — Added `MultiKBRepository`

### 2. Dual Entry Types

**Upstream:** Single `Note` model
**cascade-research:** Specialized entry types

| Type | Use Case | Key Fields |
|------|----------|------------|
| `EventEntry` | Timeline events | date, importance, actors, location, status |
| `ResearchEntry` | Research documents | entry_subtype (actor/org/theme), role, era |

**Files changed:**
- `cascade_research/models/` — New package with `EventEntry`, `ResearchEntry`
- `cascade_research/schema.py` — Enums and schemas for entry types

### 3. SQLite FTS5 Index

**Upstream:** In-memory search
**cascade-research:** Persistent SQLite with FTS5

- Full-text search with BM25 ranking
- Cross-KB search capability
- Tag and actor indexing
- Link/relationship storage for graph queries

**Files added:**
- `cascade_research/storage/database.py` — SQLite FTS5 operations
- `cascade_research/storage/index.py` — Indexing and sync
- `cascade_research/storage/migrations.py` — Schema versioning

### 4. Multiple Access Interfaces

**Upstream:** Single CLI
**cascade-research:** Four access methods

| Interface | Purpose | Entry Point |
|-----------|---------|-------------|
| Full CLI | Human researchers | `cascade-research` |
| Read CLI | AI agents (safe) | `crk-read` |
| Write CLI | AI agents (full) | `crk` |
| REST API | Web/programmatic | `crk-server` |
| Web UI | Browser access | `crk-ui` |
| MCP Server | Claude Code | `cascade_research.mcp_server` |

**Files added:**
- `cascade_research/read_cli.py` — Read-only agent CLI
- `cascade_research/write_cli.py` — Full access agent CLI
- `cascade_research/server/api.py` — FastAPI REST server
- `cascade_research/ui/` — Streamlit web interface
- `cascade_research/mcp_server.py` — Model Context Protocol server

### 5. Service Layer

**Upstream:** Business logic in CLI
**cascade-research:** Extracted service layer

- `KBService` — KB operations shared across interfaces
- `SearchService` — Search with FTS5 query sanitization

**Files added:**
- `cascade_research/services/kb_service.py`
- `cascade_research/services/search_service.py`

## Configuration Changes

### Config File Location

**Upstream:** Project-local config
**cascade-research:** User config at `~/.cascade-research/config.yaml`

### New Config Options

```yaml
knowledge_bases:
  - name: string          # KB identifier
    path: string          # Directory path
    type: events|research # KB type
    description: string   # Optional description
    read_only: bool       # Prevent modifications

settings:
  index_path: string      # SQLite database path
  github_token: string    # For private repo access
```

## Schema Changes

### Entry Frontmatter

**EventEntry** (timeline KB):
```yaml
id: event-id
title: Event Title
date: "2024-01-15"
importance: 4           # 1-5 scale
status: confirmed       # confirmed, disputed, alleged, rumored
location: Washington DC
actors:
  - Person Name
tags:
  - tag1
sources:
  - title: Source Title
    url: https://...
links:
  - target: other-entry
    relation: caused_by
```

**ResearchEntry** (research KB):
```yaml
id: actor-id
title: Actor Name
type: actor             # actor, organization, theme, mechanism, etc.
role: architect         # For actors
era: "2016-2024"
research_status: draft  # stub, partial, draft, complete, published
tags:
  - tag1
sources:
  - title: Source Title
    url: https://...
links:
  - target: other-entry
    relation: member_of
```

## Dependency Changes

### Added Dependencies

| Package | Purpose |
|---------|---------|
| `fastapi` | REST API server |
| `uvicorn` | ASGI server |
| `streamlit` | Web UI |
| `pydantic` | Data validation |
| `mcp` | Model Context Protocol |

### Development Dependencies

| Package | Purpose |
|---------|---------|
| `pytest` | Testing |
| `pytest-cov` | Coverage |
| `ruff` | Linting/formatting |
| `pre-commit` | Git hooks |

## File Structure Changes

```
cascade_research/
├── models/              # NEW: Entry models package
│   ├── base.py
│   ├── event.py
│   └── research.py
├── services/            # NEW: Business logic layer
│   ├── kb_service.py
│   └── search_service.py
├── server/              # NEW: REST API
│   └── api.py
├── storage/             # EXPANDED: Added FTS5
│   ├── database.py      # NEW
│   ├── index.py         # NEW
│   ├── migrations.py    # NEW
│   └── repository.py    # MODIFIED
├── ui/                  # NEW: Web interface
│   ├── app.py
│   ├── data.py
│   └── pages/
├── read_cli.py          # NEW: Agent CLI (read-only)
├── write_cli.py         # NEW: Agent CLI (full access)
├── mcp_server.py        # NEW: MCP server
├── config.py            # MODIFIED: Multi-KB support
└── schema.py            # MODIFIED: Extended schemas
```

## Syncing with Upstream

To incorporate upstream changes:

```bash
# Add upstream remote
git remote add upstream https://github.com/joshylchen/zettelkasten.git

# Fetch upstream
git fetch upstream

# Review changes
git log HEAD..upstream/main --oneline

# Cherry-pick or merge relevant commits
git cherry-pick <commit-hash>
```

**Areas likely to conflict:**
- `config.py` — Significantly different structure
- `models/` — Upstream uses different note model
- `storage/` — Different storage approach

**Safe to sync:**
- Documentation improvements
- Bug fixes in shared utilities
- Test improvements
