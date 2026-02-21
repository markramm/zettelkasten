"""
Tests for Agent CLI (crk).

Tests both JSON output format and command functionality.
"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import sys

from cascade_research.agent_cli import AgentCLI, main, EXIT_SUCCESS, EXIT_NOT_FOUND, EXIT_KB_NOT_FOUND
from cascade_research.storage.database import CascadeDB
from cascade_research.storage.repository import KBRepository
from cascade_research.storage.index import IndexManager
from cascade_research.config import KBConfig, KBType, CascadeConfig, Settings
from cascade_research.models import EventEntry, ResearchEntry


class TestAgentCLI:
    """Tests for AgentCLI class."""

    @pytest.fixture
    def setup(self):
        """Create test environment with sample data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create DB
            db_path = tmpdir / "index.db"

            # Create KB directories
            events_path = tmpdir / "events"
            events_path.mkdir()

            research_path = tmpdir / "research"
            research_path.mkdir()
            (research_path / "actors").mkdir()

            # Create KB configs
            events_kb = KBConfig(
                name="test-events",
                path=events_path,
                kb_type=KBType.EVENTS,
                description="Test events"
            )

            research_kb = KBConfig(
                name="test-research",
                path=research_path,
                kb_type=KBType.RESEARCH,
                description="Test research"
            )

            config = CascadeConfig(
                knowledge_bases=[events_kb, research_kb],
                settings=Settings(index_path=db_path)
            )

            # Create sample entries
            events_repo = KBRepository(events_kb)
            for i in range(3):
                event = EventEntry.create(
                    date=f"2025-01-{10+i:02d}",
                    title=f"Test Event {i}",
                    body=f"Body for event {i} about immigration policy.",
                    importance=5 + i
                )
                event.tags = ['test', 'immigration']
                event.actors = ['Stephen Miller', 'Tom Homan']
                events_repo.save(event)

            research_repo = KBRepository(research_kb)
            actor = ResearchEntry.create_actor(
                name="Stephen Miller",
                role="Immigration policy architect",
                importance=9
            )
            actor.body = "Stephen Miller is the architect of Trump immigration policy."
            actor.tags = ['trump-admin', 'immigration']
            research_repo.save(actor)

            # Create CLI with mocked config
            cli = AgentCLI()
            cli.config = config
            cli.db = CascadeDB(db_path)

            # Index
            index_mgr = IndexManager(cli.db, config)
            index_mgr.index_all()

            yield {
                'cli': cli,
                'config': config,
                'events_kb': events_kb,
                'research_kb': research_kb,
                'db': cli.db
            }

            cli.db.close()

    def test_output_json_format(self, setup):
        """Test that output is valid JSON with expected structure."""
        import io
        from contextlib import redirect_stdout

        cli = setup['cli']

        # Capture output
        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = cli.cmd_list(type('Args', (), {})())

        output = f.getvalue()
        result = json.loads(output)

        assert result['success'] is True
        assert result['exit_code'] == 0
        assert 'data' in result
        assert 'knowledge_bases' in result['data']

    def test_list_kbs(self, setup):
        """Test listing knowledge bases."""
        import io
        from contextlib import redirect_stdout

        cli = setup['cli']

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = cli.cmd_list(type('Args', (), {})())

        assert exit_code == EXIT_SUCCESS
        result = json.loads(f.getvalue())
        assert result['data']['count'] == 2

        kb_names = [kb['name'] for kb in result['data']['knowledge_bases']]
        assert 'test-events' in kb_names
        assert 'test-research' in kb_names

    def test_search(self, setup):
        """Test search command."""
        import io
        from contextlib import redirect_stdout

        cli = setup['cli']
        args = type('Args', (), {
            'query': 'immigration',
            'kb': None,
            'type': None,
            'tags': None,
            'date_from': None,
            'date_to': None,
            'limit': 20
        })()

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = cli.cmd_search(args)

        assert exit_code == EXIT_SUCCESS
        result = json.loads(f.getvalue())
        assert result['data']['count'] >= 1
        assert 'results' in result['data']

    def test_search_with_kb_filter(self, setup):
        """Test search with KB filter."""
        import io
        from contextlib import redirect_stdout

        cli = setup['cli']
        args = type('Args', (), {
            'query': 'immigration',
            'kb': 'test-events',
            'type': None,
            'tags': None,
            'date_from': None,
            'date_to': None,
            'limit': 20
        })()

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = cli.cmd_search(args)

        assert exit_code == EXIT_SUCCESS
        result = json.loads(f.getvalue())

        for r in result['data']['results']:
            assert r['kb_name'] == 'test-events'

    def test_get_entry(self, setup):
        """Test getting entry by ID."""
        import io
        from contextlib import redirect_stdout

        cli = setup['cli']

        # First search to get an ID
        search_args = type('Args', (), {
            'query': 'Stephen Miller',
            'kb': 'test-research',
            'type': None, 'tags': None, 'date_from': None, 'date_to': None, 'limit': 5
        })()

        f = io.StringIO()
        with redirect_stdout(f):
            cli.cmd_search(search_args)

        search_result = json.loads(f.getvalue())
        if search_result['data']['count'] > 0:
            entry_id = search_result['data']['results'][0]['id']

            args = type('Args', (), {
                'id': entry_id,
                'kb': 'test-research',
                'links': False
            })()

            f = io.StringIO()
            with redirect_stdout(f):
                exit_code = cli.cmd_get(args)

            assert exit_code == EXIT_SUCCESS
            result = json.loads(f.getvalue())
            assert 'entry' in result['data']

    def test_get_not_found(self, setup):
        """Test getting non-existent entry."""
        import io
        from contextlib import redirect_stdout

        cli = setup['cli']
        args = type('Args', (), {
            'id': 'nonexistent-entry-id',
            'kb': None,
            'links': False
        })()

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = cli.cmd_get(args)

        assert exit_code == EXIT_NOT_FOUND
        result = json.loads(f.getvalue())
        assert result['success'] is False
        assert 'error' in result['data']
        assert result['data']['error']['code'] == 'NOT_FOUND'

    def test_timeline(self, setup):
        """Test timeline query."""
        import io
        from contextlib import redirect_stdout

        cli = setup['cli']
        args = type('Args', (), {
            'date_from': '2025-01-01',
            'date_to': '2025-12-31',
            'importance': None,
            'actor': None,
            'limit': 50
        })()

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = cli.cmd_timeline(args)

        assert exit_code == EXIT_SUCCESS
        result = json.loads(f.getvalue())
        assert 'events' in result['data']
        assert result['data']['count'] >= 1

    def test_timeline_with_actor_filter(self, setup):
        """Test timeline with actor filter."""
        import io
        from contextlib import redirect_stdout

        cli = setup['cli']
        args = type('Args', (), {
            'date_from': None,
            'date_to': None,
            'importance': None,
            'actor': 'Miller',
            'limit': 50
        })()

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = cli.cmd_timeline(args)

        assert exit_code == EXIT_SUCCESS
        result = json.loads(f.getvalue())

        # All events should involve Miller
        for event in result['data']['events']:
            actors = event.get('actors', [])
            assert any('miller' in a.lower() for a in actors)

    def test_tags(self, setup):
        """Test getting tags."""
        import io
        from contextlib import redirect_stdout

        cli = setup['cli']
        args = type('Args', (), {
            'kb': None,
            'limit': 100
        })()

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = cli.cmd_tags(args)

        assert exit_code == EXIT_SUCCESS
        result = json.loads(f.getvalue())
        assert 'tags' in result['data']

        tag_names = [t['tag'] for t in result['data']['tags']]
        assert 'immigration' in tag_names

    def test_actors(self, setup):
        """Test getting actors."""
        import io
        from contextlib import redirect_stdout

        cli = setup['cli']
        args = type('Args', (), {'limit': 100})()

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = cli.cmd_actors(args)

        assert exit_code == EXIT_SUCCESS
        result = json.loads(f.getvalue())
        assert 'actors' in result['data']

        actor_names = [a['actor'] for a in result['data']['actors']]
        assert 'Stephen Miller' in actor_names

    def test_stats(self, setup):
        """Test getting stats."""
        import io
        from contextlib import redirect_stdout

        cli = setup['cli']
        args = type('Args', (), {})()

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = cli.cmd_stats(args)

        assert exit_code == EXIT_SUCCESS
        result = json.loads(f.getvalue())
        assert 'total_entries' in result['data']

    def test_health(self, setup):
        """Test health check."""
        import io
        from contextlib import redirect_stdout

        cli = setup['cli']
        args = type('Args', (), {'verbose': False})()

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = cli.cmd_health(args)

        assert exit_code == EXIT_SUCCESS
        result = json.loads(f.getvalue())
        assert 'healthy' in result['data']

    def test_create_event(self, setup):
        """Test creating an event."""
        import io
        from contextlib import redirect_stdout

        cli = setup['cli']
        args = type('Args', (), {
            'kb': 'test-events',
            'entry_type': 'event',
            'title': 'New Test Event',
            'body': 'This is a new event.',
            'date': '2025-02-01',
            'importance': 7,
            'tags': 'new,test',
            'actors': 'Test Actor',
            'role': None
        })()

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = cli.cmd_create(args)

        assert exit_code == EXIT_SUCCESS
        result = json.loads(f.getvalue())
        assert result['data']['created'] is True
        assert 'entry_id' in result['data']

    def test_human_output(self, setup):
        """Test human-readable output mode."""
        import io
        from contextlib import redirect_stdout

        cli = setup['cli']
        cli._human_output = True
        args = type('Args', (), {})()

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = cli.cmd_list(args)

        output = f.getvalue()

        # Should NOT be valid JSON
        try:
            json.loads(output)
            is_json = True
        except json.JSONDecodeError:
            is_json = False

        assert not is_json
        assert exit_code == EXIT_SUCCESS


class TestAgentCLIErrorHandling:
    """Test error handling and exit codes."""

    def test_structured_error_format(self):
        """Test that errors have proper structure."""
        cli = AgentCLI()

        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            exit_code = cli.error(
                code="TEST_ERROR",
                message="This is a test error",
                hint="Try this to fix it",
                exit_code=99
            )

        result = json.loads(f.getvalue())

        assert result['success'] is False
        assert result['exit_code'] == 99
        assert result['error']['code'] == 'TEST_ERROR'
        assert result['error']['message'] == 'This is a test error'
        assert result['error']['hint'] == 'Try this to fix it'


class TestAgentCLIIntegration:
    """Integration tests with actual command-line parsing."""

    def test_help_output(self):
        """Test that --help works."""
        with pytest.raises(SystemExit) as exc_info:
            with patch.object(sys, 'argv', ['crk', '--help']):
                main()
        # argparse exits with 0 for --help
        assert exc_info.value.code == 0

    def test_version_output(self):
        """Test that --version works."""
        with pytest.raises(SystemExit) as exc_info:
            with patch.object(sys, 'argv', ['crk', '--version']):
                main()
        assert exc_info.value.code == 0

    def test_no_command_shows_help(self):
        """Test that no command shows help and exits with usage error."""
        with pytest.raises(SystemExit) as exc_info:
            with patch.object(sys, 'argv', ['crk']):
                main()
        # Should exit with usage error code
        assert exc_info.value.code == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
