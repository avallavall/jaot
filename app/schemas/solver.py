"""Schemas for the solver catalog surface (``GET /solvers/available``).

Deliberately separate from ``SolverCapabilities`` in the solver domain: that one
is the adapter's full self-description, this one is the projection the UI is
allowed to act on. ``app/api/v2/solvers.py`` documents which flags are exposed
and which are withheld on purpose.
"""

from pydantic import BaseModel, Field


class SolverCapabilityFlags(BaseModel):
    """What a solver can actually deliver, as the UI reads it."""

    sensitivity: bool = Field(description="Shadow prices / reduced costs")
    warm_start: bool = Field(description="A re-solve can be seeded from the incumbent")
    quadratic: bool = Field(description="Models carrying quadratic terms can run")
    progress: bool = Field(description="Per-incumbent streaming (Live Solve)")


class AvailableSolver(BaseModel):
    """One entry of the solver listing.

    ``reason`` and ``retry_after`` ride only on an unavailable solver (D-11);
    ``capabilities`` is optional because a solver that is listable must stay
    listable even when its declared capabilities cannot be read.
    """

    name: str
    available: bool
    description: str
    capabilities: SolverCapabilityFlags | None = None
    reason: str | None = None
    retry_after: int | None = None


class AvailableSolversResponse(BaseModel):
    """Solvers this server can run right now, with live availability."""

    solvers: list[AvailableSolver]
