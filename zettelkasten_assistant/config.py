import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ZK_NOTES_DIR = Path(os.getenv("ZK_NOTES_DIR", "./data/notes")).resolve()
ZK_DB_PATH = Path(os.getenv("ZK_DB_PATH", "./data/db/zettelkasten.db")).resolve()
ZK_HOST = os.getenv("ZK_HOST", "127.0.0.1")
ZK_PORT = int(os.getenv("ZK_PORT", "8088"))

ZK_LLM_PROVIDER = os.getenv("ZK_LLM_PROVIDER", "stub")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "")

# Summary Configuration
ZK_SUMMARY_MAX_LENGTH = int(os.getenv("ZK_SUMMARY_MAX_LENGTH", "280"))

# Ensure directories exist
ZK_NOTES_DIR.mkdir(parents=True, exist_ok=True)
ZK_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
