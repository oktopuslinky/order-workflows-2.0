"""Environment loading from a ``.env`` file.

Credentials (e.g. ``NVIDIA_API_KEY``) are read from the process environment.
:func:`load_environment` populates that environment from a local ``.env`` file
using python-dotenv. It is cached so repeated calls are cheap and idempotent.
"""

from __future__ import annotations

from functools import lru_cache

from dotenv import find_dotenv, load_dotenv


@lru_cache(maxsize=1)
def load_environment() -> None:
    """Load variables from the nearest ``.env`` file into ``os.environ`` once.

    Existing environment variables are never overridden, so real deployment
    secrets always take precedence over a local ``.env`` file.
    """
    load_dotenv(find_dotenv(usecwd=True), override=False)
