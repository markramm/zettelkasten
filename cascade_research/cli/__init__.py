"""
cascade-research CLI

Command-line interface for managing knowledge bases.
Split into submodules for maintainability:
- kb_commands: Knowledge base management (list, add, remove, discover, validate)
- index_commands: Search index management (build, sync, stats, embed, health)
- search_commands: Search command with file fallback
"""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ..config import (
    CONFIG_FILE,
    KBType,
    Repository,
    auto_discover_kbs,
    load_config,
    save_config,
)
from ..models import EventEntry, ResearchEntry
from .index_commands import index_app
from .kb_commands import kb_app
from .search_commands import register_search_command

app = typer.Typer(
    name="cascade-research",
    help="Multi-KB research infrastructure for citizen journalists and AI agents",
    no_args_is_help=True,
)
console = Console()

# Register sub-apps
app.add_typer(kb_app, name="kb")
app.add_typer(index_app, name="index")

# Repository management commands
repo_app = typer.Typer(help="Repository management (multi-KB repos)")
app.add_typer(repo_app, name="repo")

# Authentication commands
auth_app = typer.Typer(help="Authentication (GitHub OAuth)")
app.add_typer(auth_app, name="auth")

# Register search command
register_search_command(app)


# =============================================================================
# Get command
# =============================================================================


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


# =============================================================================
# Config command
# =============================================================================


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


# =============================================================================
# Serve command
# =============================================================================


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

    from ..github_auth import pull_repo

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
    from ..github_auth import check_github_auth

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
    from ..github_auth import start_oauth_flow

    success, message = start_oauth_flow(client_id, client_secret)
    if success:
        console.print(f"[green]✓[/green] {message}")
    else:
        console.print(f"[red]✗[/red] {message}")
        raise typer.Exit(1)


@auth_app.command("github-logout")
def auth_github_logout():
    """Remove GitHub authentication."""
    from ..github_auth import clear_github_auth

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

    from ..github_auth import GitHubAuth, save_github_auth

    auth = GitHubAuth(
        client_id=client_id,
        client_secret=client_secret,
    )
    save_github_auth(auth)

    console.print("\n[green]✓[/green] Credentials saved.")
    console.print("Run 'cascade-research auth github-login' to authenticate.")


# =============================================================================
# MCP Server Commands
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
    from ..server.mcp_server import CascadeMCPServer

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

    if config_path is None:
        config_path = Path.home() / ".claude" / "claude_desktop_config.json"

    config_path = config_path.expanduser()

    cascade_exe = shutil.which("cascade-research")
    if not cascade_exe:
        cascade_exe = "python -m cascade_research.cli"
        console.print("[yellow]Warning: cascade-research not in PATH, using module path[/yellow]")

    if config_path.exists():
        with open(config_path) as f:
            claude_config = json.load(f)
    else:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        claude_config = {}

    if "mcpServers" not in claude_config:
        claude_config["mcpServers"] = {}

    claude_config["mcpServers"]["cascade-research"] = {
        "command": cascade_exe if "python" not in cascade_exe else "python",
        "args": ["-m", "cascade_research.cli", "mcp"] if "python" in cascade_exe else ["mcp"],
        "env": {},
    }

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
