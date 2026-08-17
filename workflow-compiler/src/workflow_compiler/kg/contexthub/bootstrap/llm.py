"""OpenAI-compatible LLM client for graph enrichment (stdlib only)."""
from __future__ import annotations

from typing import Protocol

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)


class LlmError(RuntimeError):
    pass


# Provider presets — default OpenAI-compatible base URL + which env var holds the
# key. Any endpoint that speaks the OpenAI /v1 API works (OpenAI, NVIDIA build.
# nvidia.com, vLLM, Ollama, LM Studio, an on-prem "OpenServer" gateway, …), so a
# new backend is a config change, not a code change.
_PROVIDER_PRESETS: dict[str, tuple[str, str]] = {
    "openai":     ("https://api.openai.com/v1",           "OPENAI_API_KEY"),
    "nvidia":     ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY"),
    "groq":       ("https://api.groq.com/openai/v1",      "GROQ_API_KEY"),
    "ollama":     ("http://127.0.0.1:11434/v1",           ""),
    "vllm":       ("http://127.0.0.1:8000/v1",            ""),
    "lmstudio":   ("http://127.0.0.1:1234/v1",            ""),
    "openserver": ("http://127.0.0.1:8080/v1",            ""),  # on-prem/DGX gateway
    "local":      ("http://127.0.0.1:8080/v1",            ""),
}

# Providers that run locally and do not require an API key.
_LOCAL_PROVIDERS = {"ollama", "vllm", "lmstudio", "openserver", "local"}


def uses_restricted_params(model: str) -> bool:
    """True for models that reject ``temperature``/``top_p`` and rename
    ``max_tokens`` → ``max_completion_tokens`` (OpenAI reasoning / o-series /
    gpt-5, and the gpt-oss family)."""
    m = (model or "").lower().rsplit("/", 1)[-1]
    return m.startswith(("o1", "o3", "o4", "gpt-5")) or "gpt-oss" in m


@dataclass
class LlmConfig:
    api_url: str
    api_key: str
    model: str = ""
    provider: str = "openai"
    temperature: float = 0.1
    max_tokens: int = 1024
    timeout_seconds: int = 180

    @classmethod
    def from_env(
        cls,
        *,
        api_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        provider: str | None = None,
    ) -> LlmConfig | None:
        prov = (
            provider
            or os.environ.get("CONTEXTHUB_LLM_PROVIDER")
            or os.environ.get("LLM_PROVIDER")
            or "openai"
        ).strip().lower()
        preset_url, preset_key_var = _PROVIDER_PRESETS.get(prov, ("", ""))

        url = (
            api_url
            or os.environ.get("CONTEXTHUB_LLM_API_URL")
            or os.environ.get("LLM_API_BASE")
            or os.environ.get("OPENAI_BASE_URL")
            or os.environ.get("NVIDIA_BASE_URL")
            or os.environ.get("LLM_API_URL")
            or preset_url
        )
        key = (
            api_key
            or os.environ.get("CONTEXTHUB_LLM_API_KEY")
            or (os.environ.get(preset_key_var) if preset_key_var else None)
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("NVIDIA_API_KEY")
            or os.environ.get("LLM_API_KEY")
            or ""
        )
        mdl = (
            model
            or os.environ.get("CONTEXTHUB_LLM_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or os.environ.get("NVIDIA_MODEL")
            or os.environ.get("LLM_MODEL")
            or ""
        )
        if not url:
            return None
        # Cloud providers need a key; local backends (Ollama/vLLM/…) do not.
        if not key and prov not in _LOCAL_PROVIDERS:
            return None
        return cls(api_url=url, api_key=key, model=mdl, provider=prov)


def failover_chain_from_env() -> list[str]:
    """Parse ``CONTEXTHUB_LLM_FAILOVER`` into an ordered provider chain.

    ``nvidia,groq`` → ["nvidia", "groq"]. Unset/empty → [] (single-client
    behavior, exactly as before M3). Duplicates collapse keeping first position.
    """
    raw = os.environ.get("CONTEXTHUB_LLM_FAILOVER", "")
    chain: list[str] = []
    for part in raw.split(","):
        name = part.strip().lower()
        if name and name not in chain:
            chain.append(name)
    return chain


def config_for_provider(name: str) -> LlmConfig | None:
    """Resolve one failover-chain entry to an ``LlmConfig``.

    The entry matching the session's configured provider goes through
    ``LlmConfig.from_env()`` wholesale, so entry 0 of ``nvidia,groq`` on an
    NVIDIA-configured stack is byte-identical to today's single client. Other
    entries resolve from their preset only — the generic URL/key env overrides
    (LLM_API_BASE, NVIDIA_API_KEY fallback, …) must NOT bleed into them, or a
    Groq entry could inherit the NVIDIA key and 401 forever.

    Per-provider model: ``CONTEXTHUB_LLM_MODEL_<NAME>`` (e.g.
    ``CONTEXTHUB_LLM_MODEL_GROQ``), falling back to the global model vars.
    Unresolvable (unknown preset, missing key, no model) → None; the caller
    skips the entry with a warning.
    """
    name = name.strip().lower()
    per_model = os.environ.get(f"CONTEXTHUB_LLM_MODEL_{name.upper()}") or None
    current = (
        os.environ.get("CONTEXTHUB_LLM_PROVIDER")
        or os.environ.get("LLM_PROVIDER")
        or "openai"
    ).strip().lower()
    if name == current:
        return LlmConfig.from_env(provider=name, model=per_model)
    preset_url, preset_key_var = _PROVIDER_PRESETS.get(name, ("", ""))
    if not preset_url:
        return None
    key = os.environ.get(preset_key_var, "") if preset_key_var else ""
    if not key and name not in _LOCAL_PROVIDERS:
        return None
    model = (
        per_model
        or os.environ.get("CONTEXTHUB_LLM_MODEL")
        or os.environ.get("LLM_MODEL")
        or ""
    )
    if not model:
        return None
    return LlmConfig(api_url=preset_url, api_key=key, model=model, provider=name)


_THINK_BLOCK = re.compile(r"<think>[\s\S]*?</think>", re.IGNORECASE)
_THINK_UNCLOSED = re.compile(r"<think>[\s\S]*$", re.IGNORECASE)


def extract_json_object(text: str) -> dict:
    stripped = text.strip()
    # Local instruct models (e.g. Nemotron) may wrap answers in think tags.
    stripped = _THINK_BLOCK.sub("", stripped).strip()
    stripped = _THINK_UNCLOSED.sub("", stripped).strip()
    fence = _JSON_FENCE.search(stripped)
    if fence:
        stripped = fence.group(1).strip()
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(stripped[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError as exc:
            raise LlmError(f"LLM returned invalid JSON: {exc}") from exc
    raise LlmError("LLM response did not contain a JSON object")


class JsonChatClient(Protocol):
    """workflow-compiler edit: the duck type ``enrich``/``cluster`` need from a client.

    Anything with a ``chat_json`` returning a parsed JSON object (dict) can be
    injected in place of the HTTP :class:`LlmClient` — workflow-compiler passes
    a bridge over its own ``BaseLLMProvider``.
    """

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        label: str = "",
        retries: int = 3,
    ) -> dict: ...


class LlmClient:
    def __init__(self, config: LlmConfig) -> None:
        self.config = config
        self._model = config.model

    def _chat_url(self) -> str:
        base = self.config.api_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"

    def _models_url(self) -> str:
        base = self.config.api_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/models"
        return f"{base}/v1/models"

    def resolve_model(self) -> str:
        if self._model:
            return self._model
        url = self._models_url()
        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self.config.api_key}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                body = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            raise LlmError(f"Failed to list models ({exc.code}): {exc.read().decode()}") from exc
        data = body.get("data", [])
        if not data:
            raise LlmError("No models available from API")
        model_id = data[0].get("id") or data[0].get("model")
        if not model_id:
            raise LlmError("Could not parse model id from /v1/models")
        self._model = str(model_id).split("/")[-1]
        return self._model

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        label: str = "",
        retries: int = 3,
    ) -> dict:
        import time

        model = self.resolve_model()
        payload = json.dumps({
            "model": model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }).encode()
        url = self._chat_url()
        last_err: Exception | None = None
        for attempt in range(max(1, retries)):
            req = urllib.request.Request(
                url,
                data=payload,
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
                    body = json.loads(resp.read().decode())
                try:
                    content = body["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as exc:
                    raise LlmError(f"Unexpected chat response shape: {body}") from exc
                return extract_json_object(content)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="ignore")
                last_err = LlmError(
                    f"chat/completions failed{f' ({label})' if label else ''} "
                    f"({exc.code}): {detail}"
                )
                # Retry transient gateway / upstream failures.
                if exc.code not in {408, 425, 429, 500, 502, 503, 504}:
                    raise last_err from exc
            except urllib.error.URLError as exc:
                last_err = LlmError(
                    f"chat/completions unreachable{f' ({label})' if label else ''}: {exc}"
                )
            except LlmError as exc:
                # Invalid JSON can be transient on overloaded local models.
                last_err = exc
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
        assert last_err is not None
        raise last_err
