"""Conversational spec resolution — two doors to the same human gate.

* **Guided** (:mod:`workflow_compiler.dialogue.engine`) — the validator's
  findings become questions the user answers in prose. Driven by an agenda.
* **Free-form** (:mod:`workflow_compiler.dialogue.chat`) — the user says what
  they want changed and it is patched in. Driven by the user.

Both are deterministic engines over an LLM-backed agent
(:class:`workflow_compiler.agents.dialogue.DialogueAgent` and
:class:`workflow_compiler.agents.spec_chat.SpecChatAgent` respectively), and
both change specifications through the shared bookkeeping in
:mod:`workflow_compiler.dialogue.spec_ops` so they cannot drift on provenance or
on resetting the approval gate.
"""

from __future__ import annotations

from workflow_compiler.dialogue.agenda import (
    agenda_fingerprint,
    askable_findings,
    has_anything_to_ask,
    prepared_agenda_is_fresh,
)
from workflow_compiler.dialogue.chat import ChatOutcome, SpecChatEngine
from workflow_compiler.dialogue.engine import AnswerOutcome, DialogueEngine

__all__ = [
    "AnswerOutcome",
    "ChatOutcome",
    "DialogueEngine",
    "SpecChatEngine",
    "agenda_fingerprint",
    "askable_findings",
    "has_anything_to_ask",
    "prepared_agenda_is_fresh",
]
