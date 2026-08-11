"""Conversational spec resolution: ask about findings, apply prose answers.

The engine is the deterministic half of the feature — see
:mod:`workflow_compiler.dialogue.engine`. The LLM-backed half lives in
:class:`workflow_compiler.agents.dialogue.DialogueAgent`.
"""

from __future__ import annotations

from workflow_compiler.dialogue.engine import AnswerOutcome, DialogueEngine

__all__ = ["AnswerOutcome", "DialogueEngine"]
