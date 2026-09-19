class SourceStepError(RuntimeError):
    """The selected source could not produce the required base result."""


class RetrievalSourceError(RuntimeError):
    """The primary retrieval lane could not produce a recoverable base pool."""


class QueryGenerationError(RuntimeError):
    """Structured query generation exhausted its bounded repair."""


class QuerySourceError(RuntimeError):
    """The primary query could not produce a recoverable source result."""


class LLMRequestError(RuntimeError):
    """The configured LLM endpoint could not produce a usable response."""

    code = "research_workflow_failed"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code
