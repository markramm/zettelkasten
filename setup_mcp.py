#!/usr/bin/env python3
"""
Setup script for Zettelkasten Assistant MCP Server
Provides easy installation and verification of MCP server functionality.
"""

import json
import subprocess
import sys
from pathlib import Path


def check_python_version():
    """Ensure Python 3.11+ is available."""
    if sys.version_info < (3, 11):
        print(f"❌ Python 3.11+ required, found {sys.version_info.major}.{sys.version_info.minor}")
        return False
    print(f"✅ Python {sys.version_info.major}.{sys.version_info.minor} detected")
    return True


def install_dependencies():
    """Install required dependencies."""
    print("📦 Installing dependencies...")

    try:
        # Install main dependencies
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
            check=True,
            capture_output=True,
        )
        print("✅ Main dependencies installed")

        # Install MCP dependencies
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", "mcp-requirements.txt"],
            check=True,
            capture_output=True,
        )
        print("✅ MCP dependencies installed")

        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        return False


def setup_data_directories():
    """Create necessary data directories."""
    print("📁 Setting up data directories...")

    directories = [Path("data/notes"), Path("data/db")]

    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        print(f"✅ Created {directory}")

    return True


def create_env_file():
    """Create .env file if it doesn't exist."""
    env_file = Path(".env")
    env_example = Path(".env.example")

    if env_file.exists():
        print("✅ .env file already exists")
        return True

    if env_example.exists():
        # Copy from example
        with open(env_example) as f:
            content = f.read()
        with open(env_file, "w") as f:
            f.write(content)
        print("✅ Created .env from .env.example")
    else:
        # Create basic .env
        env_content = """# Zettelkasten Assistant Configuration
ZK_NOTES_DIR=./data/notes
ZK_DB_PATH=./data/db/zettelkasten.db
ZK_HOST=127.0.0.1
ZK_PORT=8088

# AI Integration (replace with your keys)
OPENAI_API_KEY=your_openai_key_here
ZK_LLM_PROVIDER=openai

# Optional: Custom API base
# OPENAI_API_BASE=https://api.openai.com/v1

# Summary Settings
ZK_SUMMARY_MAX_LENGTH=280

# UI Settings
ZK_STREAMLIT_PORT=8501
"""
        with open(env_file, "w") as f:
            f.write(env_content)
        print("✅ Created basic .env file")

    print("⚠️  Remember to update your OPENAI_API_KEY in .env for AI features")
    return True


def test_mcp_server():
    """Test MCP server functionality."""
    print("🧪 Testing MCP server...")

    try:
        # Try importing MCP dependencies
        import mcp

        print("✅ MCP library imported successfully")

        # Try importing project modules
        from zettelkasten_assistant.config import ZK_NOTES_DIR

        print("✅ Project modules imported successfully")

        # Try to run server for a moment
        print("🚀 MCP server appears ready")
        return True

    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


def generate_claude_config():
    """Generate Claude Desktop configuration."""
    current_dir = Path.cwd().absolute()
    mcp_server_path = current_dir / "mcp_server.py"
    data_notes = current_dir / "data" / "notes"
    data_db = current_dir / "data" / "db" / "zettelkasten.db"

    config = {
        "mcpServers": {
            "zettelkasten": {
                "command": "python",
                "args": [str(mcp_server_path)],
                "env": {
                    "ZK_NOTES_DIR": str(data_notes),
                    "ZK_DB_PATH": str(data_db),
                    "OPENAI_API_KEY": "your_openai_key_here",
                    "ZK_LLM_PROVIDER": "openai",
                },
            }
        }
    }

    config_file = Path("claude_desktop_config.json")
    with open(config_file, "w") as f:
        json.dump(config, f, indent=2)

    print(f"✅ Generated Claude Desktop config: {config_file}")
    print("\n📋 To use with Claude Desktop:")
    print("1. Copy the contents of claude_desktop_config.json")
    print("2. Paste into your Claude Desktop MCP configuration:")
    print("   • Windows: %APPDATA%\\Claude\\claude_desktop_config.json")
    print("   • macOS: ~/Library/Application Support/Claude/claude_desktop_config.json")
    print("3. Update the OPENAI_API_KEY with your actual key")
    print("4. Restart Claude Desktop")

    return True


def main():
    """Main setup routine."""
    print("🧠 Zettelkasten Assistant MCP Server Setup")
    print("=" * 50)

    success_steps = 0
    total_steps = 6

    # Step 1: Check Python version
    if check_python_version():
        success_steps += 1

    # Step 2: Install dependencies
    if install_dependencies():
        success_steps += 1

    # Step 3: Setup directories
    if setup_data_directories():
        success_steps += 1

    # Step 4: Create .env file
    if create_env_file():
        success_steps += 1

    # Step 5: Test MCP server
    if test_mcp_server():
        success_steps += 1

    # Step 6: Generate Claude config
    if generate_claude_config():
        success_steps += 1

    print("\n" + "=" * 50)
    print(f"Setup completed: {success_steps}/{total_steps} steps successful")

    if success_steps == total_steps:
        print("🎉 Setup completed successfully!")
        print("\n🚀 Next steps:")
        print("1. Update your OPENAI_API_KEY in .env")
        print("2. Copy Claude Desktop configuration from claude_desktop_config.json")
        print("3. Test with: python mcp_server.py")
        print("4. Or start the web interface: streamlit run ui_streamlit.py")
    else:
        print("⚠️  Setup completed with some issues. Check the errors above.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
