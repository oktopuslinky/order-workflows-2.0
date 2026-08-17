"""Knowledge bases: a corpus (docs + code + tests) indexed into a Context Hub graph.

The vendored graph engine lives in :mod:`workflow_compiler.kg.contexthub` (see its
``VENDORED.md``); everything else in the app goes through :class:`KgService`,
the typed façade: create a knowledge base from a zip/folder, (re)index it —
optionally LLM-enriched through the app's own providers — then ``retrieve``
grounded context packets, run a deterministic ``impact`` traversal, read the
``catalog`` of business ids, ``search`` anchors, or read corpus files.
"""

from workflow_compiler.kg.models import (
    KbCatalog,
    KbFile,
    KbSource,
    KbStats,
    KgFileRef,
    KgGraphSummary,
    KgImpactRow,
    KgPacket,
    KgSearchHit,
    KgSection,
    KnowledgeBase,
    KnowledgeBaseStatus,
)
from workflow_compiler.kg.service import KgService, ProviderFactory
from workflow_compiler.kg.store import (
    FileKnowledgeBaseStore,
    InMemoryKnowledgeBaseStore,
    KnowledgeBaseStore,
    validate_kb_id,
)

__all__ = [
    "FileKnowledgeBaseStore",
    "InMemoryKnowledgeBaseStore",
    "KbCatalog",
    "KbFile",
    "KbSource",
    "KbStats",
    "KgFileRef",
    "KgGraphSummary",
    "KgImpactRow",
    "KgPacket",
    "KgSearchHit",
    "KgSection",
    "KgService",
    "KnowledgeBase",
    "KnowledgeBaseStatus",
    "KnowledgeBaseStore",
    "ProviderFactory",
    "validate_kb_id",
]
