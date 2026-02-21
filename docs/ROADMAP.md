# cascade-research Development Roadmap

## Status: Active Development

Multi-KB research infrastructure for citizen journalists and AI agents. Fork of joshylchen/zettelkasten with significant architectural changes.

## Completed ✓

### Phase 1: Core Infrastructure (Commits fe98f26 → 6a850cc)

- [x] **Multi-KB Configuration System** — Support for multiple knowledge bases with different types (Events, Research)
- [x] **Entry Models** — EventEntry, ResearchEntry with full frontmatter parsing
- [x] **GitHub OAuth** — Private repository access for collaborative research
- [x] **SQLite FTS5 Storage** — Full-text search with BM25 ranking

### Phase 2: Interfaces (Commits 9e64a8b → e53d381)

- [x] **Typer CLI** — Rich command-line interface (`cascade-research`)
- [x] **MCP Server** — Model Context Protocol server for Claude Code integration
- [x] **Architecture Documentation** — System design and API reference

### Phase 3: Agent Integration (Commits 1d52c8f → 5fa6258)

- [x] **Agent-Optimized CLIs** — Permission-separated `crk-read` and `crk` commands
  - JSON output by default
  - Structured error messages with doc links
  - Semantic exit codes
  - FTS5 query sanitization for hyphenated terms
- [x] **Claude Skill** — `.claude/skills/kb/skill.md` for Claude Code discoverability
- [x] **CLI Tests** — 15 tests covering read/write operations

## Current Test Status

```
81 tests passing
├── test_config.py: 4 tests
├── test_database.py: 14 tests
├── test_models.py: 26 tests
├── test_repository.py: 7 tests
├── test_index.py: 5 tests
├── test_cli.py: 7 tests
├── test_mcp.py: 3 tests
└── test_agent_cli.py: 15 tests
```

## Planned Work

### Phase 4: REST API

- [ ] FastAPI server with OpenAPI docs
- [ ] Pagination for large result sets
- [ ] Rate limiting for public deployments
- [ ] Webhook support for index sync

### Phase 5: Web UI

- [ ] Streamlit prototype for rapid iteration
- [ ] Search interface with faceted filtering
- [ ] Timeline visualization
- [ ] Relationship graph viewer
- [ ] Entry editor with live preview

### Phase 6: FollowTheMoney Export

- [ ] FtM entity mapping for actors, organizations, events
- [ ] Export command for Aleph/OpenAleph compatibility
- [ ] Relationship export as edges

### Phase 7: Semantic Search

- [ ] Vector embeddings for entries
- [ ] sqlite-vss integration (local-first)
- [ ] Hybrid search (FTS5 + vector similarity)
- [ ] AI-powered query expansion

### Phase 8: Collaboration

- [ ] Multi-user attribution tracking
- [ ] Conflict resolution for concurrent edits
- [ ] Review workflow for entry quality
- [ ] Change notifications

## Branch Status

- **Main branch:** joshylchen/zettelkasten upstream
- **Development branch:** `cascade-research-multi-kb` on markramm/zettelkasten

## Entry Points

| Command | Module | Purpose |
|---------|--------|---------|
| `cascade-research` | `cascade_research.cli:main` | Full CLI (Typer) |
| `crk` | `cascade_research.write_cli:main` | Agent CLI (full access) |
| `crk-read` | `cascade_research.read_cli:main` | Agent CLI (read-only) |

## Configuration

```yaml
# ~/.cascade-research/config.yaml
knowledge_bases:
  - name: timeline
    path: /path/to/timeline
    type: events
  - name: research-kb
    path: /path/to/research-kb
    type: research

settings:
  index_path: ~/.cascade-research/index.db
```

## Key Files

```
cascade_research/
├── config.py           # Configuration loading and validation
├── models.py           # EventEntry, ResearchEntry models
├── cli.py              # Typer CLI (cascade-research)
├── read_cli.py         # Read-only agent CLI (crk-read)
├── write_cli.py        # Full access agent CLI (crk)
├── mcp_server.py       # MCP protocol server
└── storage/
    ├── database.py     # SQLite FTS5 operations
    ├── repository.py   # File-based KB operations
    └── index.py        # Indexing and sync

.claude/skills/kb/
└── skill.md            # Claude Code skill documentation

docs/
├── ARCHITECTURE.md     # System design
└── ROADMAP.md          # This file
```
