"""Shared dependency-free errors for CLI and execution-host helpers."""


class ProjectError(RuntimeError):
    """Raised when a Gorak project operation fails."""
