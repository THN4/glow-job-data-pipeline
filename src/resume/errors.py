"""Resume-domain errors that do not depend on an API framework."""

from __future__ import annotations


class ResumeProcessingError(Exception):
    """A safe, user-facing resume-processing error identified by a stable code."""

    def __init__(self, code: str, message: str | None = None):
        self.code = code
        self.message = message
        super().__init__(message or code)
