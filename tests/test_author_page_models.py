"""GET /organizations/{org_id}/models — every model an author published is reachable.

The endpoint took a fixed fifty and returned them as the whole list, while the
profile beside it reported the real total. The biggest author on the site
published 102 models and 52 of them could not be opened from their own page:
there was no pager, no "load more", and nothing saying more existed.
"""

from app.models import ModelCategory, ModelProject, ModelProjectListing

_URL = "/api/v2/organizations"


def _publish(db, org, *, pid: str, executions: int) -> None:
    """One published, public listing owned by ``org``."""
    db.add(ModelProject(id=pid, organization_id=org.id, name=f"Proj {pid}", status="active"))
    db.flush()
    db.add(
        ModelProjectListing(
            model_project_id=pid,
            name=pid,
            display_name=f"Model {pid}",
            description="Test",
            category=ModelCategory.GENERAL.value,
            generator_type="generic",
            input_schema={"type": "object"},
            input_fields=[],
            example_input={},
            version="1.0.0",
            status="published",
            is_public=True,
            author_organization_id=org.id,
            total_executions=executions,
        )
    )
    db.commit()


def _publish_many(db, org, count: int) -> None:
    for i in range(count):
        # Descending executions so the order is deterministic and readable.
        _publish(db, org, pid=f"author_page_{i:03d}", executions=count - i)


# CONTRACT-TEST: the author page can reach every model the profile counts
def test_every_published_model_is_reachable_by_paging(
    authenticated_client, db_session, test_organization
) -> None:
    _publish_many(db_session, test_organization, 120)

    profile = authenticated_client.get(f"{_URL}/{test_organization.id}/public").json()
    assert profile["total_models_published"] == 120

    seen: list[str] = []
    for page in (1, 2, 3):
        response = authenticated_client.get(
            f"{_URL}/{test_organization.id}/models", params={"page": page, "page_size": 50}
        )
        assert response.status_code == 200
        seen.extend(item["id"] for item in response.json())

    assert len(seen) == 120
    # No model repeated across pages and none dropped between them: the order
    # has a total tiebreaker, so the offsets line up.
    assert len(set(seen)) == 120


def test_the_first_page_is_what_the_endpoint_used_to_return(
    authenticated_client, db_session, test_organization
) -> None:
    """Fifty, newest-busiest first — the old behaviour, now page one of several."""
    _publish_many(db_session, test_organization, 60)

    response = authenticated_client.get(f"{_URL}/{test_organization.id}/models")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 50
    assert body[0]["id"] == "author_page_000"


def test_a_page_past_the_end_is_empty_rather_than_an_error(
    authenticated_client, db_session, test_organization
) -> None:
    _publish_many(db_session, test_organization, 3)

    response = authenticated_client.get(f"{_URL}/{test_organization.id}/models", params={"page": 9})
    assert response.status_code == 200
    assert response.json() == []


def test_a_page_size_over_the_ceiling_is_refused(authenticated_client, test_organization) -> None:
    """The ceiling is what keeps one request from walking the whole catalogue."""
    response = authenticated_client.get(
        f"{_URL}/{test_organization.id}/models", params={"page_size": 500}
    )
    assert response.status_code == 422
