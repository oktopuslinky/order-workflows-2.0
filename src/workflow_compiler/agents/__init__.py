"""Compilation agents. Each agent depends only on BaseLLMProvider."""

from __future__ import annotations

from workflow_compiler.agents.cvpa import CVPAClassifierAgent, CVPAOutput
from workflow_compiler.agents.discovery import (
    WorkflowDiscovery,
    WorkflowDiscoveryAgent,
)
from workflow_compiler.agents.fact_extraction import (
    FactExtraction,
    FactExtractionAgent,
)
from workflow_compiler.agents.graph_builder import GraphBuilderAgent
from workflow_compiler.agents.review import WorkflowReviewAgent
from workflow_compiler.agents.temporal import (
    TemporalDesignOutput,
    TemporalGeneratorAgent,
)

__all__ = [
    "CVPAClassifierAgent",
    "CVPAOutput",
    "FactExtraction",
    "FactExtractionAgent",
    "GraphBuilderAgent",
    "TemporalDesignOutput",
    "TemporalGeneratorAgent",
    "WorkflowDiscovery",
    "WorkflowDiscoveryAgent",
    "WorkflowReviewAgent",
]
