"""Resolve resource and mutable data locations without CLI side effects."""
import os
from pathlib import Path

RESOURCE_ROOT = Path(__file__).resolve().parent.parent


def user_data_dir():
    override = os.environ.get('APPSHELF_DATA_DIR')
    if override:
        return Path(override).expanduser().resolve()
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'AppShelf'
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / 'AppShelf'
