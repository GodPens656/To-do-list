"""Authorization widgets.

The implementation remains on ``Utils`` to preserve its shared UI state and
avoid changing the existing event-handler code during the refactor.
"""

from .miscs import Utils


class AuthWidgets(Utils):
    """Authorization UI facade preserving the existing shared widget state."""

__all__ = ["AuthWidgets", "Utils"]
