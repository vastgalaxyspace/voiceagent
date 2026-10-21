"""Filesystem locations anchored to the repository, not the launch directory."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VOICE_CLIENT_ROOT = PROJECT_ROOT / 'tools' / 'voice_client'
REPORTS_ROOT = PROJECT_ROOT / 'reports'
