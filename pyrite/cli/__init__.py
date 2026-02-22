"""
pyrite CLI

Command-line interface for managing knowledge bases.
Split into submodules for maintainability:
- kb_commands: Knowledge base management (list, add, remove, discover, validate)
- index_commands: Search index management (build, sync, stats, embed, health)
- search_commands: Search command with file fallback
- repo_commands: Repository collaboration (subscribe, fork, sync, unsubscribe, status)
"""

from pathlib import Path

import typer
from rich.console import Console

from ..config import (
    CONFIG_FILE,
    Repository,
    auto_discover_kbs,
    load_config,
    save_config,
)
from ..storage.repository import KBRepository
from .index_commands import index_app
from .kb_commands import kb_app
from .repo_commands import repo_collab_app
from .search_commands import register_search_command

app = typer.Typer(
    name="pyrite",
    help="Multi-KB research infrastructure for citizen journalists and AI agents",
    no_args_is_help=True,
)
console = Console()

# Register sub-apps
app.add_typer(kb_app, name="kb")
app.add_typer(index_app, name="index")

# Repository management — collaboration app with subscribe/fork/sync/unsubscribe/status/list
# Plus legacy add/remove commands added below
app.add_typer(repo_collab_app, name="repo")

# Authentication commands
auth_app = typer.Typer(help="Authentication (GitHub OAuth)")
app.add_typer(auth_app, name="auth")

# Register search command
register_search_command(app)

# Register plugin CLI commands
try:
    from ..plugins import get_registry

    for name, command in get_registry().get_all_cli_commands():
        if hasattr(command, "registered_commands"):
            # It's a Typer app — register as sub-app
            app.add_typer(command, name=name)
        else:
            # It's a single command callback
            app.command(name)(command)
except Exception:
    pass  # Plugin loading shouldn't break the CLI


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

        repo = KBRepository(kb)
        for md_file in repo.list_files():
            try:
                entry = repo._load_entry(md_file)

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
# Legacy Repository Commands (add/remove for local repos)
# =============================================================================


@repo_collab_app.command("add")
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
    """Add a local repository to the registry."""
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
                console.print(f"  [green]Discovered KB:[/green] {kb.name} ({kb.kb_type})")

    save_config(config)
    console.print(f"[green]Added repository:[/green] {repo_name}")


@repo_collab_app.command("remove")
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


# =============================================================================
# Authentication Commands
# =============================================================================


@auth_app.command("status")
def auth_status():
    """Check GitHub authentication status."""
    from ..github_auth import check_github_auth

    valid, message = check_github_auth()
    if valid:
        console.print(f"[green]{message}")
    else:
        console.print(f"[yellow]![/yellow] {message}")


@auth_app.command("whoami")
def auth_whoami():
    """Show current user identity."""
    from ..storage.database import PyriteDB

    config = load_config()
    db = PyriteDB(config.settings.index_path)
    try:
        from ..services.user_service import UserService

        user_service = UserService(db)
        user = user_service.get_current_user()

        if user.get("github_id", 0) == 0:
            console.print("[yellow]Not authenticated with GitHub[/yellow]")
            console.print("Identity: [bold]local[/bold] (no GitHub auth)")
            console.print("\nRun 'pyrite auth github-login' to authenticate.")
        else:
            console.print(f"[bold cyan]{user['github_login']}[/bold cyan]")
            if user.get("display_name"):
                console.print(f"  Name: {user['display_name']}")
            if user.get("email"):
                console.print(f"  Email: {user['email']}")
            console.print(f"  GitHub ID: {user['github_id']}")
    finally:
        db.close()


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
        console.print(f"[green]{message}")
    else:
        console.print(f"[red]{message}")
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

    console.print("\n[green]Credentials saved.")
    console.print("Run 'pyrite auth github-login' to authenticate.")


# =============================================================================
# MCP Server Commands
# =============================================================================


@app.command("mcp")
def mcp_server():
    """
    Start the MCP (Model Context Protocol) server.

    This runs the write-tier server over stdio for integration with Claude Code
    and other MCP-compatible AI agents.

    Tools exposed (write tier):
    - kb_list, kb_search, kb_get, kb_timeline, kb_backlinks, kb_tags, kb_stats, kb_schema
    - kb_create, kb_update, kb_delete
    """
    from ..server.mcp_server import PyriteMCPServer

    console.print("[dim]Starting MCP server (write tier) on stdio...[/dim]", err=True)
    server = PyriteMCPServer(tier="write")
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

    Adds pyrite to Claude Code's MCP server configuration.
    """
    import json
    import shutil

    if config_path is None:
        config_path = Path.home() / ".claude" / "claude_desktop_config.json"

    config_path = config_path.expanduser()

    pyrite_exe = shutil.which("pyrite-admin")
    if not pyrite_exe:
        pyrite_exe = "python -m pyrite.admin_cli"
        console.print("[yellow]Warning: pyrite-admin not in PATH, using module path[/yellow]")

    if config_path.exists():
        with open(config_path) as f:
            claude_config = json.load(f)
    else:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        claude_config = {}

    if "mcpServers" not in claude_config:
        claude_config["mcpServers"] = {}

    claude_config["mcpServers"]["pyrite"] = {
        "command": pyrite_exe if "python" not in pyrite_exe else "python",
        "args": ["-m", "pyrite.admin_cli", "mcp"] if "python" in pyrite_exe else ["mcp"],
        "env": {},
    }

    with open(config_path, "w") as f:
        json.dump(claude_config, f, indent=2)

    console.print(f"[green]MCP server configured in {config_path}[/green]")
    console.print("\nRestart Claude Code to load the new MCP server.")
    console.print("\nAvailable tools:")
    console.print("  • kb_list - List knowledge bases")
    console.print("  • kb_search - Full-text search across KBs")
    console.print("  • kb_get - Get entry by ID")
    console.print("  • kb_schema - Get KB schema for agents")
    console.print("  • kb_create - Create new entry")
    console.print("  • kb_update - Update entry")
    console.print("  • kb_delete - Delete entry")
    console.print("  • kb_timeline - Query timeline events")
    console.print("  • kb_backlinks - Find entries linking to an entry")
    console.print("  • kb_tags - Get all tags with counts")
    console.print("  • kb_stats - Get index statistics")
    console.print("  • kb_index_sync - Sync index (admin tier)")
    console.print("  • kb_manage - Manage KBs (admin tier)")


def main():
    app()


if __name__ == "__main__":
    main()
