"""HTTP-level tests for LLM conversation document attachments.

These go through the full ASGI stack on purpose: the global
BodyLimitMiddleware (50 MB) must NOT swallow uploads that the attachment
endpoint itself is designed to accept (50 MB cap enforced in
app/api/v2/llm.py from document_extraction.MAX_FILE_SIZE). The attachments
route is exempt from the global body limit so real-world PDFs reach the
endpoint instead of being rejected with a generic 413.
"""

from __future__ import annotations


def _create_conversation(authenticated_client) -> str:
    response = authenticated_client.post("/api/v2/llm/conversations", json={})
    assert response.status_code == 201
    conv_id: str = response.json()["id"]
    return conv_id


class TestAttachmentUploadSizeContract:
    # CONTRACT-TEST: uploads up to the attachment cap (50 MB) must reach the
    # endpoint and succeed — the body-limit middleware exempts the attachments
    # route (the global body limit is also 50 MB).
    def test_upload_passes_global_body_limit(self, authenticated_client) -> None:
        conv_id = _create_conversation(authenticated_client)

        # 2 MB of plain text — comfortably under the 50 MB attachment cap; the
        # attachments route is exempt from the global body limit either way.
        content = (b"optimization model context line\n" * 65_536)[: 2 * 1024 * 1024]
        response = authenticated_client.post(
            f"/api/v2/llm/conversations/{conv_id}/attachments",
            files={"file": ("context.txt", content, "text/plain")},
        )

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["filename"] == "context.txt"
        # Extraction truncates at 100K chars — what matters here is that the
        # request was not rejected by the middleware with a generic 413.
        assert data["char_count"] > 0

    def test_upload_over_50mb_rejected_by_endpoint_cap(self, authenticated_client) -> None:
        conv_id = _create_conversation(authenticated_client)

        content = b"x" * (50 * 1024 * 1024 + 1024)  # just over the 50 MB cap
        response = authenticated_client.post(
            f"/api/v2/llm/conversations/{conv_id}/attachments",
            files={"file": ("huge.txt", content, "text/plain")},
        )

        assert response.status_code == 413
        # The endpoint's own message, not the middleware's generic body
        assert "Maximum size" in response.json()["detail"]

    def test_non_upload_routes_keep_global_limit(self, authenticated_client) -> None:
        """The exemption is surgical: a >50 MB JSON body on a normal route still 413s."""
        big_payload = {"title": "x" * (50 * 1024 * 1024 + 1)}
        response = authenticated_client.post("/api/v2/llm/conversations", json=big_payload)
        assert response.status_code == 413
        assert response.json()["detail"] == "Request body too large"
