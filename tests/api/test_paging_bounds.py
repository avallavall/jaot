"""A list endpoint refuses a page it cannot serve, with a 422 and not a 500.

``page=0`` on the API key list, or a negative ``skip`` or ``limit`` on the
builder and version lists, reached PostgreSQL as a negative OFFSET or LIMIT.
PostgreSQL refused it and the client got a 500.
"""

from __future__ import annotations

import pytest

_LISTS = [
    "/api/v2/keys/?page=0",
    "/api/v2/keys/?page_size=-5",
    "/api/v2/builder/?skip=-1",
    "/api/v2/builder/?limit=-1",
    "/api/v2/builder/doc_x/versions/?skip=-1",
    "/api/v2/builder/doc_x/versions/?limit=0",
    "/api/v2/projects/mp_x/versions?skip=-1",
    "/api/v2/projects/mp_x/versions?limit=-3",
]


@pytest.mark.parametrize("url", _LISTS)
def test_an_impossible_page_is_a_422(authenticated_client, url: str) -> None:
    response = authenticated_client.get(url)
    assert response.status_code == 422, (url, response.status_code, response.text[:200])


def test_a_normal_page_still_works(authenticated_client) -> None:
    response = authenticated_client.get("/api/v2/keys/?page=1&page_size=500")
    assert response.status_code == 200
    assert response.json()["page_size"] == 100
