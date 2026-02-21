# Knowledge Base Access Skill

Access the cascade-research knowledge bases for timeline events, actors, organizations, and research entries.

## Available CLIs

### `crk-read` - Read-only (safe for automated workflows)
```bash
crk-read list                           # List all KBs
crk-read search "query"                 # Full-text search
crk-read get <entry-id>                 # Get entry by ID
crk-read timeline --from=2025-01-01     # Timeline events
crk-read tags                           # All tags with counts
crk-read actors                         # All actors with counts
```

### `crk` - Full access (read + write + admin)
```bash
# Read (same as crk-read)
crk search "immigration policy" --kb=timeline
crk get miller-stephen --with-links
crk timeline --actor=Miller --min-importance=7

# Write
crk create --kb=timeline --type=event --title="Title" --date=2025-01-20
crk update <id> --kb=timeline --body="Updated content"
crk delete <id> --kb=timeline

# Admin
crk index build                         # Rebuild search index
crk index sync                          # Incremental sync
crk index health                        # Check index health
```

## Output Format

All commands output JSON:
```json
{
  "ok": true,
  "code": 0,
  "data": { ... }
}
```

On error:
```json
{
  "ok": false,
  "code": 2,
  "error": {
    "code": "NOT_FOUND",
    "message": "Entry 'foo' not found",
    "hint": "crk search 'foo'",
    "docs": "https://github.com/markramm/zettelkasten/blob/main/docs/ARCHITECTURE.md"
  }
}
```

## Common Workflows

### Research an actor
```bash
crk-read search "Stephen Miller"
crk-read get miller-stephen --with-links
crk-read timeline --actor=Miller
```

### Find events in a date range
```bash
crk-read timeline --from=2025-01-20 --to=2025-01-31 --min-importance=7
```

### Explore tags and connections
```bash
crk-read tags --limit=20
crk-read search --tags=immigration,cbp
```

### Create a new timeline event
```bash
crk create --kb=timeline --type=event \
  --title="DHS Announces Policy Change" \
  --date=2025-02-01 \
  --importance=8 \
  --actors="Kristi Noem,Tom Homan" \
  --tags="dhs,immigration"
```

## Exit Codes
- 0: Success
- 1: Usage error
- 2: Entry not found
- 3: KB not found
- 4: Permission denied
- 5: Validation error
- 10: Index error
- 99: Other error

## Knowledge Bases

Typical KBs in this project:
- `timeline` - Dated events with actors and importance scores
- `research-kb` - Actors, organizations, themes, mechanisms
