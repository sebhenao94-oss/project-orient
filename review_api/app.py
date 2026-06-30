"""FastAPI app for the W5 Review Agent — read + session/commit endpoints (Track B).

The app is written entirely against the ``ReviewStore`` contract and selects a
concrete store by the ``REVIEW_STORE`` env var:

* ``fake`` (default) — ``FakeReviewStore``, seeded from the committed W4 snapshots;
  no credentials required. This is what runs in dev and in the offline tests.
* ``postgres`` — Track A's ``pipeline.review_store.PostgresReviewStore``, wired in
  at the Friday convergence behind the same interface.

Run locally:  ``uvicorn review_api.app:app --reload``  → docs at ``/docs``.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import List, Optional
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from pipeline.models import NormalizationStatus
from review_api.contracts import (
    ActionRequest,
    ActionResult,
    CommitResult,
    DiscrepancyGroupBy,
    DiscrepancyQuery,
    DiscrepancyStatus,
    DiscrepancyView,
    EquipmentQuery,
    EquipmentReviewItem,
    EquipmentSort,
    RelationshipQuery,
    RelationshipView,
    ReviewStore,
    SessionState,
    SeverityHint,
    ZoneQuery,
    ZoneReviewItem,
)
from review_api.fake_store import FakeReviewStore


# --------------------------------------------------------------------------- #
# Store selection / dependency injection
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _build_store() -> ReviewStore:
    backend = os.environ.get("REVIEW_STORE", "fake").lower()
    if backend == "postgres":
        # Imported lazily so the fake/offline path never needs a DB driver.
        from pipeline.review_store import PostgresReviewStore  # type: ignore

        return PostgresReviewStore()
    return FakeReviewStore()


def get_store() -> ReviewStore:
    """FastAPI dependency. Override in tests via ``app.dependency_overrides``."""
    return _build_store()


app = FastAPI(
    title="Project ORIENT — Review Agent API",
    version="0.1.0",
    description=(
        "Read and session/commit endpoints for the human review agent. Nothing "
        "reaches a production table except through an explicit session commit."
    ),
)


# --------------------------------------------------------------------------- #
# Request bodies
# --------------------------------------------------------------------------- #
class OpenSessionRequest(BaseModel):
    property_id: UUID
    floor: str
    reviewer: Optional[str] = None


# --------------------------------------------------------------------------- #
# Read endpoints
# --------------------------------------------------------------------------- #
@app.get("/equipment", response_model=List[EquipmentReviewItem], tags=["read"])
def list_equipment(
    sort: EquipmentSort = EquipmentSort.CONFIDENCE_ASC,
    status: Optional[NormalizationStatus] = None,
    min_confidence: Optional[float] = None,
    review_required: Optional[bool] = None,
    store: ReviewStore = Depends(get_store),
) -> List[EquipmentReviewItem]:
    """List equipment for review. Defaults to lowest-confidence-first (riskiest)."""
    query = EquipmentQuery(
        sort=sort,
        status=status,
        min_confidence=min_confidence,
        review_required=review_required,
    )
    return store.list_equipment(query)


@app.get("/relationships", response_model=RelationshipView, tags=["read"])
def list_relationships(
    property_id: Optional[str] = None,
    floor: Optional[str] = None,
    store: ReviewStore = Depends(get_store),
) -> RelationshipView:
    """Relationship edges plus orphans and validator errors.

    Renders the current empty edge set correctly (0 edges / 50 orphans) and fills
    in once the deferred tiling pass produces edges.
    """
    query = RelationshipQuery(property_id=property_id, floor=floor)
    return store.list_relationships(query)


@app.get("/discrepancies", response_model=DiscrepancyView, tags=["read"])
def list_discrepancies(
    group_by: Optional[DiscrepancyGroupBy] = None,
    severity: Optional[SeverityHint] = None,
    status: Optional[DiscrepancyStatus] = None,
    store: ReviewStore = Depends(get_store),
) -> DiscrepancyView:
    """The gap report with server-side grouping, filtering, and headline rollups."""
    query = DiscrepancyQuery(group_by=group_by, severity=severity, status=status)
    return store.list_discrepancies(query)


@app.get("/zones", response_model=List[ZoneReviewItem], tags=["read"])
def list_zones(
    floor: Optional[str] = None,
    store: ReviewStore = Depends(get_store),
) -> List[ZoneReviewItem]:
    """Zone/orientation review items. Empty until W7."""
    return store.list_zones(ZoneQuery(floor=floor))


# --------------------------------------------------------------------------- #
# Session / action endpoints
# --------------------------------------------------------------------------- #
@app.post("/sessions", response_model=SessionState, status_code=201, tags=["session"])
def open_session(
    body: OpenSessionRequest,
    store: ReviewStore = Depends(get_store),
) -> SessionState:
    """Open a review sitting for one property/floor."""
    return store.open_session(body.property_id, body.floor, body.reviewer)


@app.get("/sessions/{session_id}", response_model=SessionState, tags=["session"])
def get_session(
    session_id: UUID,
    store: ReviewStore = Depends(get_store),
) -> SessionState:
    """Current session state (pending/approved/rejected counts)."""
    try:
        return store.get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown session {session_id}")


@app.post(
    "/sessions/{session_id}/actions", response_model=ActionResult, tags=["session"]
)
def record_action(
    session_id: UUID,
    request: ActionRequest,
    store: ReviewStore = Depends(get_store),
) -> ActionResult:
    """Record an approve/edit/reject decision. Nothing is committed yet."""
    try:
        return store.record_action(session_id, request)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown session {session_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post(
    "/sessions/{session_id}/commit", response_model=CommitResult, tags=["session"]
)
def commit_session(
    session_id: UUID,
    store: ReviewStore = Depends(get_store),
) -> CommitResult:
    """Atomically commit the session: approved/edited → production, rejected → log."""
    try:
        return store.commit_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown session {session_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
