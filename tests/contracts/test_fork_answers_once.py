"""One project, one model — whichever path asks for it.

A generator-backed fork stores a model rendered once, at fork time, and the
solve path re-renders from the source card. When the card is corrected the two
stop agreeing: the studio reads the stored draft and posts it to /solve/async
while /execute and /preview build a different model from the card, for the same
project id, with no warning on either side. 17 cards carry generator_params, so
every project forked from one of them before that release was in that state.

The other half of the same seam: the draft endpoint has never refused an edit
to a generator-backed project, and the solve path re-rendered regardless, so a
model somebody wrote in the studio was discarded the moment they solved it.

Both directions are pinned here.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.models import Organization
from app.models.model_project import ModelProject, ModelProjectListing
from app.services import model_project_service as svc

pytestmark = pytest.mark.contract


_CARD = {
    "model_project_id": "mp_fork_card",
    "name": "fork-card",
    "display_name": "Fork Card",
    "description": "A published generator-backed card.",
    "category": "logistics",
    "status": "published",
    "is_public": True,
    "generator_type": "knapsack",
    "input_fields": [{"name": "items", "type": "array"}],
    "example_input": {
        "items": [
            {"name": "a", "value": 10, "weight": 3},
            {"name": "b", "value": 7, "weight": 2},
        ],
        "capacity": 4,
    },
}


def _card(db: Session, org: Organization) -> ModelProjectListing:
    """The published card, plus the project row its listing hangs off."""
    db.add(
        ModelProject(
            id=_CARD["model_project_id"],
            organization_id=org.id,
            name="Fork Card source",
            status="active",
        )
    )
    db.flush()
    listing = ModelProjectListing(**_CARD)
    db.add(listing)
    db.flush()
    return listing


def _fork(db: Session, org: Organization, model_json: dict) -> ModelProject:
    """A project seeded from the card, the way create-from-marketplace does."""
    return svc.create_seeded(
        db,
        org_id=org.id,
        user_id=None,
        name="My fork",
        problem_json=model_json,
        source_type="marketplace",
        source_ref="mp_fork_card",
    )


# CONTRACT-TEST: an untouched fork is refreshed from its card, so both paths agree.
def test_a_fork_nobody_edited_follows_the_card(
    authenticated_client, db_session: Session, test_organization: Organization
) -> None:
    _card(db_session, test_organization)
    # A stale draft: what the card rendered before it was corrected.
    stale = {
        "name": "knapsack",
        "variables": [{"name": "a", "type": "binary"}],
        "objective": {"sense": "maximize", "expression": "10*a"},
        "constraints": [],
    }
    project = _fork(db_session, test_organization, stale)
    db_session.commit()

    assert svc.draft_is_untouched(project), "a fresh fork must read as untouched"

    resp = authenticated_client.post(
        f"/api/v2/models/{project.id}/preview",
        json={"input_data": _CARD["example_input"]},
    )
    assert resp.status_code == 200, resp.text
    # The card's real model has both items; the stale draft had one.
    assert {v["name"] for v in resp.json()["variables"]} == {"a", "b"}

    db_session.refresh(project)
    assert {v["name"] for v in project.draft_model_json["variables"]} == {"a", "b"}, (
        "the stored draft still holds the stale model, so the studio would show "
        "one model while the API solves another"
    )
    assert svc.draft_is_untouched(project), "a refresh must not look like a user edit"


# CONTRACT-TEST: a draft the user edited is never overwritten, and is what solves.
def test_an_edited_draft_wins_over_the_card(
    authenticated_client, db_session: Session, test_organization: Organization
) -> None:
    _card(db_session, test_organization)
    project = _fork(db_session, test_organization, {"name": "seed", "variables": []})
    db_session.commit()

    mine = {
        "name": "mine",
        "variables": [{"name": "z", "type": "continuous", "lower_bound": 0}],
        "objective": {"sense": "maximize", "expression": "3*z"},
        "constraints": [{"name": "cap", "expression": "z <= 5"}],
    }
    resp = authenticated_client.put(
        f"/api/v2/projects/{project.id}/draft", json={"model_json": mine}
    )
    assert resp.status_code == 200, resp.text

    db_session.refresh(project)
    assert not svc.draft_is_untouched(project), "an edited draft must read as edited"

    # The card can no longer speak for this project: preview has nothing to render.
    resp = authenticated_client.post(
        f"/api/v2/models/{project.id}/preview", json={"input_data": {}}
    )
    assert resp.status_code == 422, resp.text

    db_session.refresh(project)
    assert project.draft_model_json == mine, "the user's model was overwritten"


# CONTRACT-TEST: a project seeded before seed_content_hash keeps its own draft.
def test_a_project_from_before_the_column_is_left_alone(
    db_session: Session, test_organization: Organization
) -> None:
    project = _fork(db_session, test_organization, {"name": "old", "variables": []})
    project.seed_content_hash = None  # what the migration leaves on existing rows
    db_session.flush()

    assert not svc.draft_is_untouched(project)
    assert not svc.refresh_seeded_draft(db_session, project, {"name": "new", "variables": []})
    assert project.draft_model_json == {"name": "old", "variables": []}
