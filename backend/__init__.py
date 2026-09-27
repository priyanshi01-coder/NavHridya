"""NAVHRIDYA backend package.

Importing this loads .env first, so every module below sees the configured
values no matter which entry point started the app.
"""
from . import config  # noqa: F401  - side effect: populates os.environ
