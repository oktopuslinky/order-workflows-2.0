"""NVIDIA Nemotron provider.

Nemotron models are served through an OpenAI-compatible API (e.g. NVIDIA NIM /
``integrate.api.nvidia.com``). This class only sets vendor defaults; the base
URL, model, and credentials all remain overridable, and no vendor SDK is used.
"""

from __future__ import annotations

from typing import ClassVar

from workflow_compiler.llm.providers.openai_compatible import OpenAICompatibleProvider


class NemotronProvider(OpenAICompatibleProvider):
    """OpenAI-compatible provider preconfigured for NVIDIA Nemotron models."""

    name: ClassVar[str] = "nemotron"

    DEFAULT_BASE_URL: ClassVar[str] = "https://integrate.api.nvidia.com/v1"
    DEFAULT_MODEL: ClassVar[str] = "nvidia/llama-3.3-nemotron-super-49b-v1"
    API_KEY_ENV: ClassVar[str] = "NVIDIA_API_KEY"
    # Nemotron "super" models are reasoning models; disable reasoning by default
    # so structured extraction returns clean JSON quickly. Override if you want
    # chain-of-thought ("detailed thinking on").
    DEFAULT_SYSTEM_PREAMBLE: ClassVar[str] = "detailed thinking off"
