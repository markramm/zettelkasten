"""Tests for service layer."""

import tempfile
from pathlib import Path

import pytest

from cascade_research.config import CascadeConfig, KBConfig, KBType, Settings
from cascade_research.services import KBService, SearchService
from cascade_research.storage.database import CascadeDB


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test data."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def test_config(temp_dir):
    """Create test configuration."""
    kb_path = temp_dir / "research"
    kb_path.mkdir()
    (kb_path / "actors").mkdir()

    timeline_path = temp_dir / "timeline"
    timeline_path.mkdir()

    return CascadeConfig(
        knowledge_bases=[
            KBConfig(
                name="test-research",
                path=kb_path,
                kb_type=KBType.RESEARCH,
            ),
            KBConfig(
                name="test-timeline",
                path=timeline_path,
                kb_type=KBType.EVENTS,
            ),
        ],
        settings=Settings(index_path=temp_dir / "index.db"),
    )


@pytest.fixture
def test_db(test_config):
    """Create test database."""
    db = CascadeDB(test_config.settings.index_path)
    yield db
    db.close()


class TestSearchService:
    """Tests for SearchService."""

    def test_sanitize_simple_query(self):
        """Simple queries pass through unchanged."""
        assert SearchService.sanitize_fts_query("hello world") == "hello world"

    def test_sanitize_hyphenated_term(self):
        """Hyphenated terms are quoted."""
        result = SearchService.sanitize_fts_query("alex-jones")
        assert result == '"alex-jones"'

    def test_sanitize_multiple_hyphens(self):
        """Multiple hyphenated terms are all quoted."""
        result = SearchService.sanitize_fts_query("alex-jones 2024-01-15")
        assert result == '"alex-jones" "2024-01-15"'

    def test_sanitize_preserves_fts_operators(self):
        """FTS5 operators are preserved."""
        query = 'trump AND "border wall"'
        assert SearchService.sanitize_fts_query(query) == query

    def test_sanitize_preserves_quoted_phrases(self):
        """Already quoted phrases are preserved."""
        query = '"alex-jones"'
        assert SearchService.sanitize_fts_query(query) == query

    def test_sanitize_handles_or_operator(self):
        """OR operator is preserved."""
        query = "trump OR biden"
        assert SearchService.sanitize_fts_query(query) == query

    def test_sanitize_handles_not_operator(self):
        """NOT operator is preserved."""
        query = "trump NOT fake"
        assert SearchService.sanitize_fts_query(query) == query

    def test_search_normalizes_all_kbs(self, test_db, test_config):
        """'All KBs' is normalized to None."""
        service = SearchService(test_db)
        # This should not raise - it normalizes the kb_name
        results = service.search("test", kb_name="All KBs")
        assert isinstance(results, list)


class TestKBService:
    """Tests for KBService."""

    def test_list_kbs(self, test_db, test_config):
        """list_kbs returns all configured KBs."""
        service = KBService(test_config, test_db)

        kbs = service.list_kbs()

        assert len(kbs) == 2
        names = {kb["name"] for kb in kbs}
        assert "test-research" in names
        assert "test-timeline" in names

    def test_list_kbs_includes_stats(self, test_db, test_config):
        """list_kbs includes entry counts."""
        service = KBService(test_config, test_db)

        kbs = service.list_kbs()

        for kb in kbs:
            assert "entries" in kb
            assert "indexed" in kb
            assert "type" in kb

    def test_get_kb_found(self, test_db, test_config):
        """get_kb returns config for existing KB."""
        service = KBService(test_config, test_db)

        kb = service.get_kb("test-research")

        assert kb is not None
        assert kb.name == "test-research"

    def test_get_kb_not_found(self, test_db, test_config):
        """get_kb returns None for missing KB."""
        service = KBService(test_config, test_db)

        kb = service.get_kb("nonexistent")

        assert kb is None

    def test_create_entry_research(self, test_db, test_config):
        """create_entry creates research entry."""
        service = KBService(test_config, test_db)

        entry = service.create_entry(
            kb_name="test-research",
            entry_id="test-actor",
            title="Test Actor",
            entry_type="actor",
            body="Test body",
            tags=["test"],
        )

        assert entry.id == "test-actor"
        assert entry.title == "Test Actor"

    def test_create_entry_event(self, test_db, test_config):
        """create_entry creates event entry."""
        service = KBService(test_config, test_db)

        entry = service.create_entry(
            kb_name="test-timeline",
            entry_id="test-event",
            title="Test Event",
            entry_type="event",
            date="2024-01-15",
            importance=4,
        )

        assert entry.id == "test-event"
        assert entry.date == "2024-01-15"

    def test_create_entry_read_only_fails(self, test_db, temp_dir):
        """create_entry fails on read-only KB."""
        config = CascadeConfig(
            knowledge_bases=[
                KBConfig(
                    name="readonly-kb",
                    path=temp_dir / "readonly",
                    kb_type=KBType.RESEARCH,
                    read_only=True,
                ),
            ],
            settings=Settings(index_path=temp_dir / "index.db"),
        )
        (temp_dir / "readonly").mkdir()

        service = KBService(config, test_db)

        with pytest.raises(ValueError, match="read-only"):
            service.create_entry(
                kb_name="readonly-kb",
                entry_id="test",
                title="Test",
                entry_type="actor",
            )

    def test_get_entry(self, test_db, test_config):
        """get_entry retrieves created entry."""
        service = KBService(test_config, test_db)

        # Create an entry
        service.create_entry(
            kb_name="test-research",
            entry_id="get-test",
            title="Get Test",
            entry_type="actor",
        )

        # Retrieve it
        entry = service.get_entry("get-test", "test-research")

        assert entry is not None
        assert entry["title"] == "Get Test"

    def test_get_entry_searches_all_kbs(self, test_db, test_config):
        """get_entry without kb_name searches all KBs."""
        service = KBService(test_config, test_db)

        service.create_entry(
            kb_name="test-research",
            entry_id="search-all-test",
            title="Search All Test",
            entry_type="actor",
        )

        # Search without specifying KB
        entry = service.get_entry("search-all-test")

        assert entry is not None
        assert entry["title"] == "Search All Test"

    def test_delete_entry(self, test_db, test_config):
        """delete_entry removes entry from file and index."""
        service = KBService(test_config, test_db)

        service.create_entry(
            kb_name="test-research",
            entry_id="delete-test",
            title="Delete Test",
            entry_type="actor",
        )

        result = service.delete_entry("delete-test", "test-research")

        assert result is True
        assert service.get_entry("delete-test", "test-research") is None
