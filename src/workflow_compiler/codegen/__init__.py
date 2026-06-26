"""Deterministic code generation from canonical design artifacts.

Code generators in this package are pure functions of an already-produced,
reviewed design — they use **no LLM**. They are the executable counterpart to
the design agents: where ``TemporalGeneratorAgent`` emits a specification, the
Temporal code generator mechanically renders that specification into runnable
Temporal SDK source via templates.
"""

from __future__ import annotations

from workflow_compiler.codegen.temporal import TemporalPythonCodeGenerator

__all__ = ["TemporalPythonCodeGenerator"]
