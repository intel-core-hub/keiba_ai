from __future__ import annotations


class ProviderError(RuntimeError):
    """Base error for evidence data providers."""


class ProviderDataError(ProviderError):
    """Provider returned malformed or unusable data."""


class ProviderUnavailableError(ProviderError):
    """Provider data could not be reached or does not exist."""
