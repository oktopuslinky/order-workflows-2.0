"""Session-authenticated provider for the local eGPU "LLM API Gateway".

The gateway (branded "MakersLab"/"openserver") fronts a TensorRT-LLM multi-model
backend behind a custom **password-session** auth: you ``POST /auth/login`` with
``{email, password}`` and receive an ``openserver_session`` cookie (replayable as
a bearer token) that expires. Inference itself is OpenAI-compatible, so this
provider reuses its parent's chat wire format and adds only:

* lazy login + expiry-aware refresh + one 401-triggered re-authentication;
* model discovery via the gateway's public ``GET /auth/config`` (no auth); and
* lazy resolution of the gateway's advertised default model when none is set.

No vendor SDK is used; everything goes over the shared ``httpx`` client.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Sequence
from typing import Any, ClassVar
from urllib.parse import urlsplit, urlunsplit

import httpx

from workflow_compiler.env import load_environment
from workflow_compiler.exceptions import (
    LLMProviderError,
    ProviderConnectionError,
    ProviderHTTPError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from workflow_compiler.llm.providers.openai_compatible import OpenAICompatibleProvider
from workflow_compiler.llm.types import ChatMessage, LLMResponse


class GatewaySessionProvider(OpenAICompatibleProvider):
    """OpenAI-compatible provider with password-session auth for the local gateway."""

    name: ClassVar[str] = "local"

    EMAIL_ENV: ClassVar[str] = "LLM_GATEWAY_EMAIL"
    PASSWORD_ENV: ClassVar[str] = "LLM_GATEWAY_PASSWORD"
    SESSION_COOKIE: ClassVar[str] = "openserver_session"
    #: Placeholder held in config until the gateway's default model is resolved.
    _UNRESOLVED_MODEL: ClassVar[str] = "__gateway_default__"
    #: Refresh the session this many seconds before it actually expires.
    _EXPIRY_MARGIN: ClassVar[float] = 30.0

    def __init__(
        self,
        *,
        email: str | None = None,
        password: str | None = None,
        model: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Read credentials (args or env) and defer model resolution when unset."""
        load_environment()
        self._email = email or os.environ.get(self.EMAIL_ENV)
        self._password = password or os.environ.get(self.PASSWORD_ENV)
        self._needs_model = model is None
        self._token: str | None = None
        self._token_expiry: float | None = None
        self._authenticated = False
        self._auth_lock = asyncio.Lock()
        super().__init__(model=model or self._UNRESOLVED_MODEL, **kwargs)

    # -- auth ---------------------------------------------------------------

    def _origin(self) -> str:
        """Return ``scheme://host:port`` (auth routes live at the root, not /v1)."""
        parts = urlsplit(self._config.base_url)
        return urlunsplit((parts.scheme, parts.netloc, "", "", ""))

    async def _login(self) -> None:
        """Authenticate against ``/auth/login`` and capture the session token."""
        if not self._email or not self._password:
            raise LLMProviderError(
                f"{self.name} gateway requires {self.EMAIL_ENV} and {self.PASSWORD_ENV} "
                "(register at the gateway's /ui/)."
            )
        client = self._ensure_client()
        try:
            resp = await client.post(
                f"{self._origin()}/auth/login",
                json={"email": self._email, "password": self._password},
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"{self.name} login timed out: {exc}") from exc
        except httpx.TransportError as exc:
            raise ProviderConnectionError(f"{self.name} login transport error: {exc}") from exc

        if resp.status_code >= 400:
            raise ProviderHTTPError(resp.status_code, resp.text[:500])
        try:
            body = resp.json()
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(f"{self.name} login returned non-JSON: {exc}") from exc
        if not body.get("authenticated"):
            raise LLMProviderError(f"{self.name} gateway rejected the supplied credentials.")

        # The token arrives as a cookie; the client jar also retains it, so a
        # missing value here still authenticates subsequent same-client calls.
        self._token = resp.cookies.get(self.SESSION_COOKIE) or client.cookies.get(
            self.SESSION_COOKIE
        )
        expires_in = body.get("expires_in")
        self._token_expiry = (
            time.monotonic() + float(expires_in) - self._EXPIRY_MARGIN
            if isinstance(expires_in, (int, float))
            else None
        )

    def _session_fresh(self) -> bool:
        return self._authenticated and (
            self._token_expiry is None or time.monotonic() < self._token_expiry
        )

    async def _ensure_session(self) -> None:
        if self._session_fresh():
            return
        async with self._auth_lock:
            if self._session_fresh():
                return
            await self._login()
            self._authenticated = True

    async def _relogin(self) -> None:
        async with self._auth_lock:
            self._authenticated = False
            await self._login()
            self._authenticated = True

    def _auth_headers(self) -> dict[str, str]:
        headers = super()._auth_headers()
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    # -- transport (session-aware) ------------------------------------------

    async def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        await self._ensure_session()
        try:
            return await super()._post(endpoint, payload)
        except ProviderHTTPError as exc:
            if exc.status_code == 401:
                await self._relogin()
                return await super()._post(endpoint, payload)
            raise

    async def _get(self, endpoint: str) -> dict[str, Any]:
        await self._ensure_session()
        try:
            return await super()._get(endpoint)
        except ProviderHTTPError as exc:
            if exc.status_code == 401:
                await self._relogin()
                return await super()._get(endpoint)
            raise

    # -- model resolution ---------------------------------------------------

    async def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Resolve the gateway's default model (if unset) before chatting."""
        await self._ensure_model()
        return await super().chat(
            messages, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode
        )

    async def _ensure_model(self) -> None:
        if not self._needs_model:
            return
        cfg = await self._fetch_auth_config()
        default = cfg.get("model")
        if not default:
            raise LLMProviderError(
                f"{self.name} gateway did not advertise a default model; set a model explicitly."
            )
        self._config.model = default
        self._needs_model = False

    # -- discovery (unauthenticated) ----------------------------------------

    async def list_models(self) -> list[str]:
        """Return model ids from the gateway's public ``/auth/config`` (no auth)."""
        cfg = await self._fetch_auth_config()
        models = cfg.get("models") or []
        return [m["id"] for m in models if isinstance(m, dict) and "id" in m]

    async def _fetch_auth_config(self) -> dict[str, Any]:
        """GET the gateway's public config (models + advertised default), no session."""
        client = self._ensure_client()
        try:
            resp = await client.get(f"{self._origin()}/auth/config")
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"{self.name} config request timed out: {exc}") from exc
        except httpx.TransportError as exc:
            raise ProviderConnectionError(f"{self.name} config transport error: {exc}") from exc
        return self._decode(resp)
