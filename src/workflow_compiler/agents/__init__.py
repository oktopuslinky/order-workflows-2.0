"""Compilation agents. Each agent depends only on BaseLLMProvider."""

from __future__ import annotations

from workflow_compiler.agents.cvpa import CVPAClassifierAgent, CVPAOutput
from workflow_compiler.agents.discovery import (
    WorkflowDiscovery,
    WorkflowDiscoveryAgent,
)
from workflow_compiler.agents.ensemble import (
    DISCOVERY_SPEC,
    FACTS_SPEC,
    ConsensusMergeAgent,
    StageSpec,
)
from workflow_compiler.agents.fact_extraction import (
    FactExtraction,
    FactExtractionAgent,
)
from workflow_compiler.agents.graph_builder import GraphBuilderAgent
from workflow_compiler.agents.ideal_prose import IdealProseAgent, IdealProseOutput
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
from workflow_compiler.agents.segmenter import (
    DocumentSegmentation,
    WorkflowSegmenterAgent,
    canonical_name,
)
from workflow_compiler.agents.temporal import (
    TemporalDesignOutput,
    TemporalGeneratorAgent,
)
from workflow_compiler.agents.temporal_code import TemporalCodeGeneratorAgent

__all__ = [
    "DISCOVERY_SPEC",
    "FACTS_REVIEW_SPEC",
    "FACTS_SPEC",
    "METADATA_REVIEW_SPEC",
    "CVPAClassifierAgent",
    "CVPAOutput",
    "ConsensusMergeAgent",
    "DocumentSegmentation",
    "FactExtraction",
    "FactExtractionAgent",
    "FactsPatchApplier",
    "GraphBuilderAgent",
    "IdealProseAgent",
    "IdealProseOutput",
    "MetadataPatchApplier",
    "ReviewPass",
    "ReviewPipelineAgent",
    "ReviewSpec",
    "StageSpec",
    "TemporalCodeGeneratorAgent",
    "TemporalDesignOutput",
    "TemporalGeneratorAgent",
    "WorkflowDiscovery",
    "WorkflowDiscoveryAgent",
    "WorkflowReviewAgent",
    "WorkflowSegmenterAgent",
    "canonical_name",
    "rebuild_facts",
]
