"""Shared typed contracts for the Agentic IT Workforce platform.

Contracts live here so the API, workers and (through exported JSON Schema) the web app
agree on one definition of each payload.
"""

from workforce_contracts.errors import ErrorBody, ErrorCode, ErrorEnvelope

__all__ = ["ErrorBody", "ErrorCode", "ErrorEnvelope"]
