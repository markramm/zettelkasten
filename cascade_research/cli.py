"""
cascade-research CLI

Command-line interface for managing knowledge bases.
"""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import (
    CONFIG_FILE,
    KBConfig,
    KBType,
    Repository,
    auto_discover_kbs,
    load_config,
    save_config,
)
from .models import EventEntry, ResearchEntry

app = typer.Typer(
    name="cascade-research",
    help="Multi-KB research infrastructure for citizen journalists and AI agents",
    no_args_is_help=True,
)
console = Console()

# KB management commands
kb_app = typer.Typer(help="Knowledge base management")
app.add_typer(kb_app, name="kb")

# Repository management commands
repo_app = typer.Typer(help="Repository management (multi-KB repos)")
app.add_typer(repo_app, name="repo")

# Authentication commands
auth_app = typer.Typer(help="Authentication (GitHub OAuth)")
app.add_typer(auth_app, name="auth")

# Index commands
index_app = typer.Typer(help="Search index management")
app.add_typer(index_app, name="index")


@kb_app.command("list")
def kb_list(
    kb_type: str | None = typer.Option(
        None, "--type", "-t", help="Filter by type (events/research)"
    ),
):
    """List all configured knowledge bases."""
    config = load_config()

    type_filter = KBType(kb_type) if kb_type else None
    kbs = config.list_kbs(type_filter)

    if not kbs:
        console.print("[yellow]No knowledge bases configured.[/yellow]")
        console.print("Add a KB with: cascade-research kb add <path> --name <name>")
        return

    table = Table(title="Knowledge Bases")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Path")
    table.add_column("Status")

    for kb in kbs:
        errors = kb.validate()
        status = "[green]OK[/green]" if not errors else f"[red]{len(errors)} errors[/red]"
        table.add_row(kb.name, kb.kb_type.value, str(kb.path), status)

    console.print(table)


@kb_app.command("add")
def kb_add(
    path: Path = typer.Argument(..., help="Path to the knowledge base"),
    name: str | None = typer.Option(None, "--name", "-n", help="Name for the KB"),
    kb_type: str = typer.Option("research", "--type", "-t", help="KB type (events/research)"),
    description: str = typer.Option("", "--desc", "-d", help="Description"),
):
    """Add a knowledge base to the registry."""
    config = load_config()

    path = path.expanduser().resolve()
    if not path.exists():
        console.print(f"[red]Error:[/red] Path does not exist: {path}")
        raise typer.Exit(1)

    kb_name = name or path.name

    if config.get_kb(kb_name):
        console.print(f"[red]Error:[/red] KB with name '{kb_name}' already exists")
        raise typer.Exit(1)

    try:
        kb_type_enum = KBType(kb_type)
    except ValueError:
        console.print(f"[red]Error:[/red] Invalid KB type: {kb_type}. Use 'events' or 'research'")
        raise typer.Exit(1)

    kb = KBConfig(name=kb_name, path=path, kb_type=kb_type_enum, description=description)
    kb.load_kb_yaml()

    config.add_kb(kb)
    save_config(config)

    console.print(f"[green]Added KB:[/green] {kb_name} ({kb_type_enum.value}) at {path}")


@kb_app.command("remove")
def kb_remove(
    name: str = typer.Argument(..., help="Name of the KB to remove"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Remove a knowledge base from the registry."""
    config = load_config()

    kb = config.get_kb(name)
    if not kb:
        console.print(f"[red]Error:[/red] KB '{name}' not found")
        raise typer.Exit(1)

    if not force:
        confirm = typer.confirm(f"Remove KB '{name}' from registry?")
        if not confirm:
            raise typer.Abort()

    config.remove_kb(name)
    save_config(config)

    console.print(f"[green]Removed:[/green] {name}")
    console.print(f"[dim]Note: Files at {kb.path} were not deleted.[/dim]")


@kb_app.command("discover")
def kb_discover(
    search_path: Path | None = typer.Argument(None, help="Path to search for KBs"),
    add: bool = typer.Option(False, "--add", "-a", help="Add discovered KBs to registry"),
):
    """Auto-discover knowledge bases by finding kb.yaml files."""
    config = load_config()

    search_paths = [search_path] if search_path else [Path.cwd()]
    discovered = auto_discover_kbs(search_paths)

    if not discovered:
        console.print("[yellow]No KB configurations found.[/yellow]")
        return

    table = Table(title="Discovered Knowledge Bases")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Path")
    table.add_column("Status")

    for kb in discovered:
        existing = config.get_kb(kb.name)
        if existing:
            status = "[yellow]Already registered[/yellow]"
        else:
            status = "[green]New[/green]"
        table.add_row(kb.name, kb.kb_type.value, str(kb.path), status)

    console.print(table)

    if add:
        added = 0
        for kb in discovered:
            if not config.get_kb(kb.name):
                config.add_kb(kb)
                added += 1
        if added:
            save_config(config)
            console.print(f"[green]Added {added} KB(s) to registry.[/green]")


@kb_app.command("validate")
def kb_validate(
    name: str | None = typer.Argument(None, help="Name of KB to validate (all if omitted)"),
):
    """Validate knowledge base configuration and contents."""
    config = load_config()

    if name:
        kb = config.get_kb(name)
        if not kb:
            console.print(f"[red]Error:[/red] KB '{name}' not found")
            raise typer.Exit(1)
        kbs = [kb]
    else:
        kbs = config.knowledge_bases

    all_valid = True
    for kb in kbs:
        console.print(f"\n[bold]Validating {kb.name}...[/bold]")
        errors = kb.validate()
        if errors:
            all_valid = False
            for error in errors:
                console.print(f"  [red]✗[/red] {error}")
        else:
            console.print("  [green]✓[/green] Configuration valid")

            # Count entries
            if kb.path.exists():
                if kb.kb_type == KBType.EVENTS:
                    count = len(list(kb.path.glob("*.md")))
                else:
                    count = sum(1 for _ in kb.path.rglob("*.md"))
                console.print(f"  [green]✓[/green] {count} markdown files found")

    if all_valid:
        console.print("\n[green]All KBs valid.[/green]")
    else:
        console.print("\n[red]Validation errors found.[/red]")
        raise typer.Exit(1)


# Get command
@app.command("get")
def get_entry(
    entry_id: str = typer.Argument(..., help="Entry ID"),
    kb_name: str | None = typer.Option(None, "--kb", "-k", help="KB to search in"),
):
    """Get a specific entry by ID."""
    config = load_config()

    if kb_name:
        kb = config.get_kb(kb_name)
        if not kb:
            console.print(f"[red]Error:[/red] KB '{kb_name}' not found")
            raise typer.Exit(1)
        kbs = [kb]
    else:
        kbs = config.knowledge_bases

    for kb in kbs:
        if not kb.path.exists():
            continue

        for md_file in kb.path.rglob("*.md"):
            try:
                if kb.kb_type == KBType.EVENTS:
                    entry = EventEntry.load(md_file)
                else:
                    entry = ResearchEntry.load(md_file)

                if entry.id == entry_id:
                    # Display entry
                    console.print(f"\n[bold cyan]{entry.title}[/bold cyan]")
                    console.print(
                        f"[dim]KB: {kb.name} | Type: {entry.entry_type} | ID: {entry.id}[/dim]"
                    )
                    console.print(f"[dim]File: {md_file}[/dim]\n")

                    if entry.summary:
                        console.print(f"[italic]{entry.summary}[/italic]\n")

                    console.print(entry.body)

                    if entry.sources:
                        console.print(f"\n[bold]Sources ({len(entry.sources)}):[/bold]")
                        for src in entry.sources:
                            console.print(f"  • {src.title}: {src.url}")

                    return

            except Exception:
                continue

    console.print(f"[red]Error:[/red] Entry '{entry_id}' not found")
    raise typer.Exit(1)


# Config command
@app.command("config")
def show_config():
    """Show current configuration."""
    console.print(f"[bold]Config file:[/bold] {CONFIG_FILE}")
    console.print(f"[bold]Exists:[/bold] {CONFIG_FILE.exists()}")

    if CONFIG_FILE.exists():
        config = load_config()
        console.print(f"\n[bold]Knowledge Bases:[/bold] {len(config.knowledge_bases)}")
        console.print(f"[bold]Subscriptions:[/bold] {len(config.subscriptions)}")
        console.print(f"[bold]AI Provider:[/bold] {config.settings.ai_provider}")


# Serve command
@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host to bind to"),
    port: int = typer.Option(8088, "--port", "-p", help="Port to bind to"),
):
    """Start the web server."""
    console.print(f"[dim]Starting server at http://{host}:{port}...[/dim]")
    # TODO: Import and run FastAPI server
    console.print("[yellow]Web server not yet implemented.[/yellow]")


# =============================================================================
# Repository Commands
# =============================================================================


@repo_app.command("list")
def repo_list():
    """List all configured repositories."""
    config = load_config()

    if not config.repositories:
        console.print("[yellow]No repositories configured.[/yellow]")
        console.print("Add a repo with: cascade-research repo add <path> --name <name>")
        return

    table = Table(title="Repositories")
    table.add_column("Name", style="cyan")
    table.add_column("Path")
    table.add_column("Remote")
    table.add_column("Auth")
    table.add_column("KBs")

    for repo in config.repositories:
        kbs = config.get_kbs_in_repo(repo.name)
        kb_count = str(len(kbs)) if kbs else "0"
        remote = (
            repo.remote[:40] + "..."
            if repo.remote and len(repo.remote) > 40
            else (repo.remote or "-")
        )
        table.add_row(repo.name, str(repo.path), remote, repo.auth_method, kb_count)

    console.print(table)


@repo_app.command("add")
def repo_add(
    path: Path = typer.Argument(..., help="Path to the repository"),
    name: str | None = typer.Option(None, "--name", "-n", help="Name for the repo"),
    remote: str | None = typer.Option(None, "--remote", "-r", help="Git remote URL"),
    auth_method: str = typer.Option(
        "none", "--auth", "-a", help="Auth method (none/ssh/github_oauth/token)"
    ),
    discover: bool = typer.Option(
        True, "--discover/--no-discover", help="Auto-discover KBs in repo"
    ),
):
    """Add a repository to the registry."""
    config = load_config()

    path = path.expanduser().resolve()
    repo_name = name or path.name

    if config.get_repo(repo_name):
        console.print(f"[red]Error:[/red] Repository '{repo_name}' already exists")
        raise typer.Exit(1)

    repo = Repository(
        name=repo_name,
        path=path,
        remote=remote,
        auth_method=auth_method,  # type: ignore
    )

    config.add_repo(repo)

    # Auto-discover KBs if requested and path exists
    if discover and path.exists():
        discovered = auto_discover_kbs([path])
        for kb in discovered:
            if not config.get_kb(kb.name):
                kb.repo = repo_name
                kb.repo_subpath = str(kb.path.relative_to(path))
                config.add_kb(kb)
                console.print(f"  [green]Discovered KB:[/green] {kb.name} ({kb.kb_type.value})")

    save_config(config)
    console.print(f"[green]Added repository:[/green] {repo_name}")


@repo_app.command("remove")
def repo_remove(
    name: str = typer.Argument(..., help="Name of the repository"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Remove a repository from the registry."""
    config = load_config()

    repo = config.get_repo(name)
    if not repo:
        console.print(f"[red]Error:[/red] Repository '{name}' not found")
        raise typer.Exit(1)

    kbs = config.get_kbs_in_repo(name)

    if not force:
        msg = f"Remove repository '{name}'?"
        if kbs:
            msg += f" ({len(kbs)} KBs will also be removed)"
        if not typer.confirm(msg):
            raise typer.Abort()

    # Remove associated KBs
    for kb in kbs:
        config.remove_kb(kb.name)

    config.remove_repo(name)
    save_config(config)

    console.print(f"[green]Removed:[/green] {name}")
    if kbs:
        console.print(f"[dim]Also removed {len(kbs)} KB(s)[/dim]")


@repo_app.command("sync")
def repo_sync(
    name: str | None = typer.Argument(None, help="Repository to sync (all if omitted)"),
):
    """Sync repositories with their remotes (git pull)."""
    config = load_config()

    if name:
        repo = config.get_repo(name)
        if not repo:
            console.print(f"[red]Error:[/red] Repository '{name}' not found")
            raise typer.Exit(1)
        repos = [repo]
    else:
        repos = [r for r in config.repositories if r.remote]

    if not repos:
        console.print("[yellow]No repositories with remotes configured.[/yellow]")
        return

    from .github_auth import pull_repo

    for repo in repos:
        console.print(f"\n[bold]Syncing {repo.name}...[/bold]")
        if not repo.path.exists():
            console.print(f"  [yellow]Path does not exist:[/yellow] {repo.path}")
            continue

        success, message = pull_repo(repo.path)
        if success:
            console.print(f"  [green]✓[/green] {message}")
        else:
            console.print(f"  [red]✗[/red] {message}")


# =============================================================================
# Authentication Commands
# =============================================================================


@auth_app.command("status")
def auth_status():
    """Check GitHub authentication status."""
    from .github_auth import check_github_auth

    valid, message = check_github_auth()
    if valid:
        console.print(f"[green]✓[/green] {message}")
    else:
        console.print(f"[yellow]![/yellow] {message}")


@auth_app.command("github-login")
def auth_github_login(
    client_id: str | None = typer.Option(None, "--client-id", help="OAuth App client ID"),
    client_secret: str | None = typer.Option(
        None, "--client-secret", help="OAuth App client secret"
    ),
):
    """Authenticate with GitHub using OAuth."""
    from .github_auth import start_oauth_flow

    success, message = start_oauth_flow(client_id, client_secret)
    if success:
        console.print(f"[green]✓[/green] {message}")
    else:
        console.print(f"[red]✗[/red] {message}")
        raise typer.Exit(1)


@auth_app.command("github-logout")
def auth_github_logout():
    """Remove GitHub authentication."""
    from .github_auth import clear_github_auth

    if typer.confirm("Remove GitHub authentication?"):
        clear_github_auth()
        console.print("[green]GitHub authentication removed.[/green]")


@auth_app.command("github-setup")
def auth_github_setup():
    """Set up GitHub OAuth App credentials."""
    console.print("\n[bold]GitHub OAuth Setup[/bold]\n")
    console.print("To use GitHub OAuth, you need to create an OAuth App:")
    console.print("1. Go to https://github.com/settings/developers")
    console.print("2. Click 'New OAuth App'")
    console.print("3. Set the callback URL to: http://127.0.0.1:8765/callback")
    console.print("4. Copy the Client ID and Client Secret\n")

    client_id = typer.prompt("Client ID")
    client_secret = typer.prompt("Client Secret", hide_input=True)

    from .github_auth import GitHubAuth, save_github_auth

    auth = GitHubAuth(
        client_id=client_id,
        client_secret=client_secret,
    )
    save_github_auth(auth)

    console.print("\n[green]✓[/green] Credentials saved.")
    console.print("Run 'cascade-research auth github-login' to authenticate.")


# =============================================================================
# Index Commands
# =============================================================================


@index_app.command("build")
def index_build(
    kb_name: str | None = typer.Argument(None, help="KB to index (all if omitted)"),
    force: bool = typer.Option(False, "--force", "-f", help="Force full reindex"),
):
    """Build or rebuild the search index."""
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

    from .storage import CascadeDB, IndexManager

    config = load_config()
    db = CascadeDB(config.settings.index_path)
    index_mgr = IndexManager(db, config)

    if kb_name:
        kb = config.get_kb(kb_name)
        if not kb:
            console.print(f"[red]Error:[/red] KB '{kb_name}' not found")
            raise typer.Exit(1)
        kbs = [kb]
    else:
        kbs = config.knowledge_bases

    if not kbs:
        console.print("[yellow]No knowledge bases configured.[/yellow]")
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        for kb in kbs:
            if not kb.path.exists():
                console.print(f"[yellow]Skipping {kb.name}: path does not exist[/yellow]")
                continue

            task = progress.add_task(f"Indexing {kb.name}...", total=None)

            def make_progress_callback(task_id):
                def update_progress(current: int, total: int):
                    progress.update(task_id, completed=current, total=total)

                return update_progress

            count = index_mgr.index_kb(kb.name, make_progress_callback(task))
            progress.update(task, description=f"[green]✓[/green] {kb.name}: {count} entries")

    console.print("\n[green]Index build complete.[/green]")


@index_app.command("sync")
def index_sync(
    kb_name: str | None = typer.Argument(None, help="KB to sync (all if omitted)"),
):
    """Incremental sync: update index for changed files only."""
    from .storage import CascadeDB, IndexManager

    config = load_config()
    db = CascadeDB(config.settings.index_path)
    index_mgr = IndexManager(db, config)

    results = index_mgr.sync_incremental(kb_name)

    console.print("[green]Sync complete:[/green]")
    console.print(f"  Added: {results['added']}")
    console.print(f"  Updated: {results['updated']}")
    console.print(f"  Removed: {results['removed']}")


@index_app.command("stats")
def index_stats():
    """Show index statistics."""
    from .storage import CascadeDB, IndexManager

    config = load_config()
    db = CascadeDB(config.settings.index_path)
    index_mgr = IndexManager(db, config)

    stats = index_mgr.get_index_stats()

    console.print("\n[bold]Index Statistics[/bold]\n")
    console.print(f"Total entries: {stats['total_entries']}")
    console.print(f"Total tags: {stats['total_tags']}")
    console.print(f"Total links: {stats['total_links']}")

    if stats["kbs"]:
        console.print("\n[bold]Knowledge Bases:[/bold]")
        table = Table()
        table.add_column("Name", style="cyan")
        table.add_column("Type")
        table.add_column("Entries", justify="right")
        table.add_column("Last Indexed")

        for name, kb_stats in stats["kbs"].items():
            table.add_row(
                name,
                kb_stats.get("kb_type", "-"),
                str(kb_stats.get("actual_count", 0)),
                kb_stats.get("last_indexed", "-")[:19] if kb_stats.get("last_indexed") else "-",
            )
        console.print(table)


@index_app.command("embed")
def index_embed(
    kb_name: str | None = typer.Argument(None, help="KB to embed (all if omitted)"),
    force: bool = typer.Option(False, "--force", "-f", help="Re-embed all entries"),
):
    """Generate vector embeddings for semantic search."""
    from .services.embedding_service import EmbeddingService, is_available
    from .storage import CascadeDB

    if not is_available():
        console.print("[red]Error:[/red] sentence-transformers is not installed.")
        console.print("Install with: pip install cascade-research[semantic]")
        raise typer.Exit(1)

    config = load_config()
    db = CascadeDB(config.settings.index_path)

    if not db.vec_available:
        console.print("[red]Error:[/red] sqlite-vec is not installed or failed to load.")
        console.print("Install with: pip install cascade-research[semantic]")
        raise typer.Exit(1)

    # Check index has entries
    row = db.conn.execute("SELECT COUNT(*) FROM entry").fetchone()
    if row[0] == 0:
        console.print("[yellow]Index is empty. Run 'cascade-research index build' first.[/yellow]")
        raise typer.Exit(1)

    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

    svc = EmbeddingService(db, model_name=config.settings.embedding_model)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        task = progress.add_task("Embedding entries...", total=None)

        def update_progress(current: int, total: int):
            progress.update(task, completed=current, total=total)

        stats = svc.embed_all(
            kb_name=kb_name,
            force=force,
            progress_callback=update_progress,
        )

    console.print("\n[green]Embedding complete.[/green]")
    console.print(f"  Embedded: {stats['embedded']}")
    console.print(f"  Skipped: {stats['skipped']}")
    if stats["errors"]:
        console.print(f"  [red]Errors: {stats['errors']}[/red]")


@index_app.command("health")
def index_health():
    """Check index health and consistency."""
    from .storage import CascadeDB, IndexManager

    config = load_config()
    db = CascadeDB(config.settings.index_path)
    index_mgr = IndexManager(db, config)

    health = index_mgr.check_health()

    console.print("\n[bold]Index Health Check[/bold]\n")

    if (
        not health["missing_files"]
        and not health["unindexed_files"]
        and not health["stale_entries"]
    ):
        console.print("[green]✓ Index is healthy[/green]")
        return

    if health["missing_files"]:
        console.print(f"[red]Missing files ({len(health['missing_files'])}):[/red]")
        for item in health["missing_files"][:10]:
            console.print(f"  • {item['kb']}/{item['id']}")
        if len(health["missing_files"]) > 10:
            console.print(f"  ... and {len(health['missing_files']) - 10} more")

    if health["unindexed_files"]:
        console.print(f"[yellow]Unindexed files ({len(health['unindexed_files'])}):[/yellow]")
        for item in health["unindexed_files"][:10]:
            console.print(f"  • {item['kb']}/{item['id']}")
        if len(health["unindexed_files"]) > 10:
            console.print(f"  ... and {len(health['unindexed_files']) - 10} more")

    if health["stale_entries"]:
        console.print(f"[yellow]Stale entries ({len(health['stale_entries'])}):[/yellow]")
        for item in health["stale_entries"][:10]:
            console.print(f"  • {item['kb']}/{item['id']}")
        if len(health["stale_entries"]) > 10:
            console.print(f"  ... and {len(health['stale_entries']) - 10} more")

    console.print("\nRun 'cascade-research index sync' to fix issues.")


# =============================================================================
# Updated Search Command (using index)
# =============================================================================


@app.command("search")
def search(
    query: str = typer.Argument(..., help="Search query (FTS5 syntax supported)"),
    kb_name: str | None = typer.Option(None, "--kb", "-k", help="Search specific KB"),
    entry_type: str | None = typer.Option(None, "--type", "-t", help="Filter by type"),
    tag: str | None = typer.Option(None, "--tag", help="Filter by tag"),
    date_from: str | None = typer.Option(None, "--from", help="Events from date (YYYY-MM-DD)"),
    date_to: str | None = typer.Option(None, "--to", help="Events until date (YYYY-MM-DD)"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
    use_files: bool = typer.Option(False, "--files", help="Search files directly (skip index)"),
):
    """
    Search across knowledge bases.

    Supports FTS5 query syntax:
    - Simple terms: miller immigration
    - Phrases: "family separation"
    - Boolean: miller AND immigration
    - Prefix: immigr*
    - Exclude: miller -bannon
    """
    config = load_config()

    if use_files:
        # Fall back to file-based search
        _search_files(config, query, kb_name, entry_type, limit)
        return

    # Use indexed search
    from .storage import CascadeDB

    try:
        db = CascadeDB(config.settings.index_path)

        # Check if index exists
        row = db.conn.execute("SELECT COUNT(*) FROM entry").fetchone()
        if row[0] == 0:
            console.print("[yellow]Index is empty. Building index...[/yellow]")
            from .storage import IndexManager

            index_mgr = IndexManager(db, config)
            index_mgr.index_all()

        tags_list = [tag] if tag else None
        results = db.search(
            query=query,
            kb_name=kb_name,
            entry_type=entry_type,
            tags=tags_list,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

        if not results:
            console.print("[yellow]No results found.[/yellow]")
            return

        table = Table(title=f"Search Results ({len(results)})")
        table.add_column("KB", style="cyan", width=12)
        table.add_column("Type", style="green", width=10)
        table.add_column("Title", width=40)
        table.add_column("Date", width=10)
        table.add_column("Snippet", width=50)

        for r in results:
            date = r.get("date", "")[:10] if r.get("date") else ""
            snippet = r.get("snippet", "")[:100] if r.get("snippet") else ""
            table.add_row(
                r.get("kb_name", ""),
                r.get("entry_type", ""),
                r.get("title", "")[:40],
                date,
                snippet,
            )

        console.print(table)

    except Exception as e:
        console.print(f"[red]Search error:[/red] {e}")
        console.print("[dim]Falling back to file search...[/dim]")
        _search_files(config, query, kb_name, entry_type, limit)


def _search_files(config, query, kb_name, entry_type, limit):
    """File-based search fallback."""
    if kb_name:
        kb = config.get_kb(kb_name)
        if not kb:
            console.print(f"[red]Error:[/red] KB '{kb_name}' not found")
            raise typer.Exit(1)
        kbs = [kb]
    else:
        kbs = config.knowledge_bases

    if not kbs:
        console.print("[yellow]No knowledge bases configured.[/yellow]")
        return

    console.print(f"[dim]Searching for '{query}'...[/dim]")

    results = []
    for kb in kbs:
        if not kb.path.exists():
            continue

        for md_file in kb.path.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                if query.lower() in content.lower():
                    if kb.kb_type == KBType.EVENTS:
                        entry = EventEntry.load(md_file)
                    else:
                        entry = ResearchEntry.load(md_file)

                    if entry_type and entry.entry_type != entry_type:
                        continue

                    results.append((kb.name, entry, md_file))

                    if len(results) >= limit:
                        break
            except Exception:
                continue

        if len(results) >= limit:
            break

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = Table(title=f"Search Results ({len(results)})")
    table.add_column("KB", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Title")
    table.add_column("ID", style="dim")

    for kb_name, entry, _path in results:
        table.add_row(kb_name, entry.entry_type, entry.title, entry.id)

    console.print(table)


# =============================================================================
# MCP Server Command
# =============================================================================


@app.command("mcp")
def mcp_server():
    """
    Start the MCP (Model Context Protocol) server.

    This runs the server over stdio for integration with Claude Code
    and other MCP-compatible AI agents.

    Tools exposed:
    - kb_list: List knowledge bases
    - kb_search: Full-text search
    - kb_get: Get entry by ID
    - kb_create: Create new entry
    - kb_update: Update entry
    - kb_timeline: Get timeline events
    - kb_backlinks: Get backlinks to entry
    - kb_tags: Get all tags
    - kb_actors: Get all actors
    - kb_index_sync: Sync index
    """
    from .server.mcp_server import CascadeMCPServer

    console.print("[dim]Starting MCP server on stdio...[/dim]", err=True)
    server = CascadeMCPServer()
    try:
        server.run_stdio()
    finally:
        server.close()


@app.command("mcp-setup")
def mcp_setup(
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to Claude Code config (default: ~/.claude/claude_desktop_config.json)",
    ),
):
    """
    Set up MCP server integration with Claude Code.

    Adds cascade-research to Claude Code's MCP server configuration.
    """
    import json
    import shutil

    # Default config path
    if config_path is None:
        config_path = Path.home() / ".claude" / "claude_desktop_config.json"

    config_path = config_path.expanduser()

    # Find the cascade-research executable
    cascade_exe = shutil.which("cascade-research")
    if not cascade_exe:
        # Try python -m
        cascade_exe = "python -m cascade_research.cli"
        console.print("[yellow]Warning: cascade-research not in PATH, using module path[/yellow]")

    # Load existing config or create new
    if config_path.exists():
        with open(config_path) as f:
            claude_config = json.load(f)
    else:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        claude_config = {}

    # Add MCP server config
    if "mcpServers" not in claude_config:
        claude_config["mcpServers"] = {}

    claude_config["mcpServers"]["cascade-research"] = {
        "command": cascade_exe if "python" not in cascade_exe else "python",
        "args": ["-m", "cascade_research.cli", "mcp"] if "python" in cascade_exe else ["mcp"],
        "env": {},
    }

    # Write config
    with open(config_path, "w") as f:
        json.dump(claude_config, f, indent=2)

    console.print(f"[green]✓ MCP server configured in {config_path}[/green]")
    console.print("\nRestart Claude Code to load the new MCP server.")
    console.print("\nAvailable tools:")
    console.print("  • kb_list - List knowledge bases")
    console.print("  • kb_search - Full-text search across KBs")
    console.print("  • kb_get - Get entry by ID")
    console.print("  • kb_create - Create new entry")
    console.print("  • kb_timeline - Query timeline events")
    console.print("  • kb_backlinks - Find entries linking to an entry")
    console.print("  • kb_tags - Get all tags with counts")
    console.print("  • kb_actors - Get all actors from timeline")


def main():
    app()


if __name__ == "__main__":
    main()
