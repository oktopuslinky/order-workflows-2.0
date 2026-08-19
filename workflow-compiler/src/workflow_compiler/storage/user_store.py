"""Persistence for :class:`~workflow_compiler.models.user.User` accounts.

Users are stored under ``<root>/users/<user_id>.json`` with the same atomic
write pattern as :class:`~workflow_compiler.storage.project_store.FileProjectStore`.
Email lookup scans the directory — fine at local-tool scale.
"""

from __future__ import annotations

import asyncio
import copy
import tempfile
from pathlib import Path
from typing import Protocol

from workflow_compiler.exceptions import StateNotFoundError
from workflow_compiler.models.user import User
from workflow_compiler.storage.file import DEFAULT_ROOT
from workflow_compiler.storage.ids import validate_store_id


class UserStore(Protocol):
    """Persistence contract for local user accounts."""

    async def save(self, user: User) -> None:
        """Persist ``user``."""
        ...

    async def load(self, user_id: str) -> User:
        """Load a user by id, raising ``StateNotFoundError`` if absent."""
        ...

    async def get_by_email(self, email: str) -> User | None:
        """Return the user with this (lowercased) email, or ``None``."""
        ...


class FileUserStore:
    """Persist :class:`User` objects as JSON on disk."""

    def __init__(self, root: str | Path = DEFAULT_ROOT) -> None:
        """Create the store; users live in ``<root>/users``."""
        self._root = Path(root) / "users"

    def _path(self, user_id: str) -> Path:
        return self._root / f"{validate_store_id(user_id, label='user')}.json"

    def _write(self, user: User) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        target = self._path(user.user_id)
        payload = user.model_dump_json(indent=2)
        fd, tmp_name = tempfile.mkstemp(dir=self._root, suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with open(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            tmp.replace(target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def _read(self, user_id: str) -> User:
        path = self._path(user_id)
        if not path.is_file():
            raise StateNotFoundError(f"No user with id {user_id!r}.")
        return User.model_validate_json(path.read_text(encoding="utf-8"))

    def _scan_email(self, email: str) -> User | None:
        if not self._root.is_dir():
            return None
        for path in self._root.glob("*.json"):
            user = User.model_validate_json(path.read_text(encoding="utf-8"))
            if user.email == email:
                return user
        return None

    async def save(self, user: User) -> None:
        """Persist ``user`` to disk atomically."""
        await asyncio.to_thread(self._write, user)

    async def load(self, user_id: str) -> User:
        """Load a user by id, raising ``StateNotFoundError`` if absent."""
        return await asyncio.to_thread(self._read, user_id)

    async def get_by_email(self, email: str) -> User | None:
        """Return the user with this (lowercased) email, or ``None``."""
        return await asyncio.to_thread(self._scan_email, email)


class InMemoryUserStore:
    """Dict-backed user store for tests (deep-copies on save/load)."""

    def __init__(self) -> None:
        self._users: dict[str, User] = {}

    async def save(self, user: User) -> None:
        """Store a deep copy of ``user``."""
        self._users[user.user_id] = copy.deepcopy(user)

    async def load(self, user_id: str) -> User:
        """Return a deep copy of the stored user, raising if absent."""
        if user_id not in self._users:
            raise StateNotFoundError(f"No user with id {user_id!r}.")
        return copy.deepcopy(self._users[user_id])

    async def get_by_email(self, email: str) -> User | None:
        """Return the user with this (lowercased) email, or ``None``."""
        for user in self._users.values():
            if user.email == email:
                return copy.deepcopy(user)
        return None
