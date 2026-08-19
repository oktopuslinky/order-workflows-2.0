"""Project-wide exception hierarchy."""

from __future__ import annotations


class WorkflowCompilerError(Exception):
    """Base class for all workflow-compiler errors."""


class ParseError(WorkflowCompilerError):
    """Raised when a parser cannot process a source document."""


class CompilationError(WorkflowCompilerError):
    """Raised when the compilation pipeline fails."""


class ApprovalError(WorkflowCompilerError):
    """Raised when an approval transition is invalid."""


class GraphEditError(WorkflowCompilerError):
    """Raised when a graph edit operation is invalid."""


class EditPreviewStaleError(WorkflowCompilerError):
    """Raised when an edit preview no longer matches the stored project state."""


class StateNotFoundError(WorkflowCompilerError):
    """Raised when a requested workflow state does not exist in the store."""


class StaleWriteError(WorkflowCompilerError):
    """Raised when a save's ``expected_version`` no longer matches the stored record (CAS)."""


class LLMProviderError(WorkflowCompilerError):
    """Raised when an LLM provider call fails."""


class UnsupportedFormatError(ParseError):
    """Raised when no parser is registered for a requested document format."""


class FileValidationError(ParseError):
    """Raised when a source document fails validation (missing, too large, ...)."""


class EmptyDocumentError(ParseError):
    """Raised when a source document contains no bytes."""


class DocumentDecodeError(ParseError):
    """Raised when a text document cannot be decoded to a string."""


class ProviderTimeoutError(LLMProviderError):
    """Raised when an LLM provider request exceeds its timeout."""


class ProviderConnectionError(LLMProviderError):
    """Raised on a transport-level failure talking to an LLM provider."""


class ProviderHTTPError(LLMProviderError):
    """Raised when an LLM provider returns a non-success HTTP status."""

    def __init__(self, status_code: int, message: str = "") -> None:
        self.status_code = status_code
        body = f": {message}" if message else ""
        super().__init__(f"Provider returned HTTP {status_code}{body}")


class ProviderResponseError(LLMProviderError):
    """Raised when an LLM provider response cannot be parsed."""


class SchemaValidationError(LLMProviderError):
    """Raised when a structured LLM response fails schema validation."""


class PromptError(WorkflowCompilerError):
    """Base class for prompt management errors."""


class PromptNotFoundError(PromptError):
    """Raised when a requested prompt template cannot be found."""


class PromptRenderError(PromptError):
    """Raised when a prompt template cannot be rendered (e.g. missing variables)."""
