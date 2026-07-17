"""Compilation agents. Each agent depends only on BaseLLMProvider."""

from __future__ import annotations

from workflow_compiler.agents.cvpa import CVPAClassifierAgent, CVPAOutput
from workflow_compiler.agents.discovery import (
    WorkflowDiscovery,
    WorkflowDiscoveryAgent,
)
from workflow_compiler.agents.edit_interpreter import EditInterpreterAgent
from workflow_compiler.agents.fact_extraction import (
    FactExtraction,
    FactExtractionAgent,
)
from workflow_compiler.agents.graph_builder import GraphBuilderAgent
from workflow_compiler.agents.review import WorkflowReviewAgent
from workflow_compiler.agents.review_pipeline import (
    FACTS_REVIEW_SPEC,
    METADATA_REVIEW_SPEC,
    FactsPatchApplier,
    MetadataPatchApplier,
    ReviewPass,
    ReviewPipelineAgent,
    ReviewSpec,
    rebuild_facts,
)
from workflow_compiler.agents.segmentation import (
    SegmentationPatchApplier,
    WorkflowsDiscovery,
    WorkflowSegmentationAgent,
)
from workflow_compiler.agents.temporal import (
    TemporalDesignOutput,
    TemporalGeneratorAgent,
)
from workflow_compiler.agents.temporal_code import TemporalCodeGeneratorAgent

__all__ = [
    "FACTS_REVIEW_SPEC",
    "METADATA_REVIEW_SPEC",
    "CVPAClassifierAgent",
    "CVPAOutput",
    "EditInterpreterAgent",
    "FactExtraction",
    "FactExtractionAgent",
    "FactsPatchApplier",
    "GraphBuilderAgent",
    "MetadataPatchApplier",
    "ReviewPass",
    "ReviewPipelineAgent",
    "ReviewSpec",
    "SegmentationPatchApplier",
    "TemporalCodeGeneratorAgent",
    "TemporalDesignOutput",
    "TemporalGeneratorAgent",
    "WorkflowDiscovery",
    "WorkflowDiscoveryAgent",
    "WorkflowReviewAgent",
    "WorkflowSegmentationAgent",
    "WorkflowsDiscovery",
    "rebuild_facts",
]
