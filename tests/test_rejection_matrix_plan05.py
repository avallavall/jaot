def test_delete_admin_api_keys_returns_404_for_nonexistent_id(admin_client):
    """SC3 (cell #1, owner=PLAN_05): DELETE /api/v2/admin/api-keys/{key_id} -> 404 (nonexistent id).

    Reclassified from 422 to 404 per the structural-unreachability rule:
    `delete_api_key` (app/api/v2/routes/admin/api_keys.py:87) takes only a
    path string `key_id` and no Pydantic-validated body, so the 422 path is
    structurally unreachable. The 404 path is the meaningful rejection
    surface for this DELETE.
    """
    resp = admin_client.delete("/api/v2/admin/api-keys/key_does_not_exist")
    assert resp.status_code == 404


def test_patch_admin_api_keys_toggle_returns_404_for_nonexistent_id(admin_client):
    """SC3 (cell #2, owner=PLAN_05): PATCH /api/v2/admin/api-keys/{key_id}/toggle -> 404.

    Reclassified from 422 to 404: ``toggle_api_key``
    (app/api/v2/routes/admin/api_keys.py:74) takes only ``key_id: str`` path
    and no Pydantic-validated body, so 422 path is structurally unreachable.
    """
    resp = admin_client.patch("/api/v2/admin/api-keys/key_does_not_exist/toggle")
    assert resp.status_code == 404


def test_patch_admin_models_returns_422_for_wrong_body_type(admin_client):
    """SC3 (cell #3, owner=PLAN_05): PATCH /api/v2/admin/models/{model_id} -> 422.

    ``update_model_badges`` at app/api/v2/routes/admin/models.py:107 declares
    ``body: UpdateModelBadgesRequest``. A malformed body triggers Pydantic
    validation (which runs BEFORE the DB lookup in the handler).
    """
    resp = admin_client.patch(
        "/api/v2/admin/models/mod_does_not_exist",
        json={"is_official": "not-a-bool"},
    )
    assert resp.status_code == 422


def test_patch_admin_models_visibility_returns_422_for_missing_query_param(admin_client):
    """SC3 (cell #4, owner=PLAN_05): PATCH /api/v2/admin/models/{model_id}/visibility -> 422.

    ``toggle_model_visibility`` at app/api/v2/routes/admin/models.py:90 declares
    ``is_public: bool = Query(...)``. Missing the required query param triggers 422.
    """
    resp = admin_client.patch("/api/v2/admin/models/mod_does_not_exist/visibility")
    assert resp.status_code == 422


def test_patch_admin_organizations_returns_422_for_wrong_body_type(admin_client):
    """SC3 (cell #5, owner=PLAN_05): PATCH /api/v2/admin/organizations/{org_id} -> 422.

    ``update_organization`` at app/api/v2/routes/admin/organizations.py:136
    accepts a body schema. A malformed body (wrong type) triggers Pydantic 422.
    """
    resp = admin_client.patch(
        "/api/v2/admin/organizations/org_does_not_exist",
        json={"is_active": "not-a-bool"},
    )
    assert resp.status_code == 422


def test_delete_admin_organizations_returns_404_for_nonexistent_id(admin_client):
    """SC3 (cell #6, owner=PLAN_05): DELETE /api/v2/admin/organizations/{org_id} -> 404.

    Reclassified from 422 to 404: ``delete_organization``
    (app/api/v2/routes/admin/organizations.py:154) takes only a path id and
    no Pydantic-validated body, so 422 path is structurally unreachable.
    """
    resp = admin_client.delete("/api/v2/admin/organizations/org_does_not_exist")
    assert resp.status_code == 404


def test_delete_admin_organizations_verify_returns_404_for_nonexistent_id(admin_client):
    """SC3 (cell #7, owner=PLAN_05): DELETE /api/v2/admin/organizations/{org_id}/verify -> 404.

    Reclassified from 422 to 404: revoke-verification handler
    (app/api/v2/routes/profiles/admin.py:42) takes only a path id and no
    Pydantic-validated body.
    """
    resp = admin_client.delete("/api/v2/admin/organizations/org_does_not_exist/verify")
    assert resp.status_code == 404


def test_delete_admin_reviews_returns_404_for_nonexistent_id(admin_client):
    """SC3 (cell #8, owner=PLAN_05): DELETE /api/v2/admin/reviews/{review_id} -> 404.

    Reclassified from 422 to 404: delete-review-as-admin handler
    (app/api/v2/routes/profiles/admin.py:122) takes only a path id and no
    Pydantic-validated body.
    """
    resp = admin_client.delete("/api/v2/admin/reviews/rev_does_not_exist")
    assert resp.status_code == 404


def test_patch_admin_reviews_visibility_returns_422_for_missing_query_param(admin_client):
    """SC3 (cell #9, owner=PLAN_05): PATCH /api/v2/admin/reviews/{review_id}/visibility -> 422.

    ``toggle_review_visibility`` at app/api/v2/routes/profiles/admin.py:161
    declares ``visible: bool = Query(...)``. Missing the required query param
    triggers 422.
    """
    resp = admin_client.patch("/api/v2/admin/reviews/rev_does_not_exist/visibility")
    assert resp.status_code == 422


def test_put_admin_settings_commission_returns_422_for_missing_query_param(admin_client):
    """SC3 (cell #10, owner=PLAN_05): PUT /api/v2/admin/settings/commission -> 422.

    ``update_commission_rate`` at app/api/v2/routes/admin/settings.py:50 declares
    ``rate: float = Query(..., ge=0.0, le=0.50)``. Missing the required query
    param triggers 422.
    """
    resp = admin_client.put("/api/v2/admin/settings/commission")
    assert resp.status_code == 422


def test_put_admin_settings_plans_returns_422_for_malformed_body(admin_client):
    """SC3 (cell #11, owner=PLAN_05): PUT /api/v2/admin/settings/plans -> 422.

    ``update_plans`` at app/api/v2/routes/admin/settings.py:253 accepts a
    structured body schema. A malformed body (wrong shape) triggers 422.
    """
    resp = admin_client.put(
        "/api/v2/admin/settings/plans",
        json={"not_a_valid_plan_shape": True},
    )
    assert resp.status_code == 422


def test_put_admin_settings_values_returns_422_for_malformed_body(admin_client):
    """SC3 (cell #12, owner=PLAN_05): PUT /api/v2/admin/settings/values -> 422.

    ``update_values`` at app/api/v2/routes/admin/settings.py:136 accepts a
    body of settings. A malformed body shape triggers Pydantic 422.
    """
    resp = admin_client.put(
        "/api/v2/admin/settings/values",
        json="not_a_valid_dict",
    )
    assert resp.status_code == 422


def test_patch_admin_users_returns_422_for_wrong_body_type(admin_client):
    """SC3 (cell #13, owner=PLAN_05): PATCH /api/v2/admin/users/{user_id} -> 422.

    ``update_user`` at app/api/v2/routes/admin/users.py:82 accepts a body
    schema. A malformed body (wrong type for a field) triggers Pydantic 422.
    """
    resp = admin_client.patch(
        "/api/v2/admin/users/usr_does_not_exist",
        json={"is_active": "not-a-bool"},
    )
    assert resp.status_code == 422


def test_delete_admin_users_returns_404_for_nonexistent_id(admin_client):
    """SC3 (cell #14, owner=PLAN_05): DELETE /api/v2/admin/users/{user_id} -> 404.

    Reclassified from 422 to 404: ``delete_user``
    (app/api/v2/routes/admin/users.py:105) takes only a path id and no
    Pydantic-validated body.
    """
    resp = admin_client.delete("/api/v2/admin/users/usr_does_not_exist")
    assert resp.status_code == 404


def test_delete_builder_document_returns_404_for_nonexistent_id(authenticated_client):
    """SC3 (cell #15, owner=PLAN_05): DELETE /api/v2/builder/{document_id} -> 404.

    Reclassified from 422 to 404: ``delete_document`` (app/api/v2/builder.py:175)
    takes only a path id and no Pydantic-validated body.
    """
    resp = authenticated_client.delete("/api/v2/builder/doc_does_not_exist")
    assert resp.status_code == 404


def test_patch_builder_version_returns_422_for_malformed_body(authenticated_client):
    """SC3 (cell #16, owner=PLAN_05): PATCH builder version -> 422.

    ``update_version`` at app/api/v2/versions.py:123 accepts a body schema.
    A malformed body (wrong field type) triggers Pydantic 422.
    """
    resp = authenticated_client.patch(
        "/api/v2/builder/doc_does_not_exist/versions/ver_does_not_exist",
        json={"name": 12345},
    )
    assert resp.status_code == 422


def test_delete_keys_returns_404_for_nonexistent_id(authenticated_client):
    """SC3 (cell #17, owner=PLAN_05): DELETE /api/v2/keys/{key_id} -> 404.

    Reclassified from 422 to 404: ``delete_api_key`` at app/api/v2/keys.py:108
    takes only a path id and no Pydantic-validated body.
    """
    resp = authenticated_client.delete("/api/v2/keys/key_does_not_exist")
    assert resp.status_code == 404


def test_delete_llm_conversation_attachment_returns_404_for_nonexistent_id(authenticated_client):
    """SC3 (cell #18, owner=PLAN_05): DELETE LLM conversation attachment -> 404.

    Reclassified from 422 to 404: the delete handler (app/api/v2/llm.py:651)
    takes only path ids and no Pydantic-validated body.
    """
    resp = authenticated_client.delete(
        "/api/v2/llm/conversations/conv_does_not_exist/attachments/att_does_not_exist"
    )
    assert resp.status_code == 404


def test_delete_models_catalog_logo_returns_rejection(authenticated_client):
    """SC3 (cell #19, owner=PLAN_05): DELETE catalog logo -> rejection (404/503).

    Double reclassification: 422 -> 404 -> {404, 503}. The handler at
    app/api/v2/routes/models/media.py:99 calls ``_get_storage()`` BEFORE the
    DB lookup; storage is not configured in CI/test, so the path returns 503
    (Service Unavailable) before reaching the 404 model-not-found branch. Both
    statuses are legitimate rejection paths: 503 means storage service is
    unreachable; 404 means model id does not exist. We accept either as a
    valid rejection signal -- the bug is missing rejection, not the specific
    status code.
    """
    resp = authenticated_client.delete("/api/v2/models/catalog/mod_does_not_exist/logo")
    assert resp.status_code in (404, 503), (
        f"DELETE logo must reject; got {resp.status_code} {resp.text[:200]}"
    )


def test_delete_models_catalog_screenshot_returns_rejection(authenticated_client):
    """SC3 (cell #20, owner=PLAN_05): DELETE catalog screenshot -> rejection (404/503).

    Same double-reclassification as cell #19: the handler at
    app/api/v2/routes/models/media.py:149 calls ``_get_storage()`` first;
    storage is unavailable in CI/test -> 503. Otherwise 404 model not found.
    Both are legitimate rejection paths.
    """
    resp = authenticated_client.delete("/api/v2/models/catalog/mod_does_not_exist/screenshots/0")
    assert resp.status_code in (404, 503), (
        f"DELETE screenshot must reject; got {resp.status_code} {resp.text[:200]}"
    )


def test_put_models_catalog_sections_returns_rejection(authenticated_client):
    """SC3 (cell #21, owner=PLAN_05): PUT catalog sections -> rejection (404/422/503).

    ``update_sections`` at app/api/v2/routes/models/media.py:177 accepts
    ``UpdateCatalogSectionsRequest`` whose fields are all ``str | None``.
    Strongly-typed wrong values (list instead of str) force Pydantic 422.
    The handler also calls ``_get_catalog_model_for_owner`` after body
    parsing, so 404 (missing id) or 503 (storage unconfigured in CI) are
    also acceptable rejection paths.
    """
    resp = authenticated_client.put(
        "/api/v2/models/catalog/mod_does_not_exist/sections",
        json={"section_overview": ["not", "a", "string"]},
    )
    assert resp.status_code in (404, 422, 503), (
        f"PUT sections must reject; got {resp.status_code} {resp.text[:200]}"
    )


def test_delete_models_favorites_anonymous_rejected(authenticated_client):
    """SC3 (cell #22, owner=PLAN_05): DELETE favorites - idempotent + anon rejected (401).

    ``remove_favorite`` (app/api/v2/routes/models/favorites.py:93) is an
    idempotent delete - it returns 200 even if the favorite does not exist
    (no 404 rejection path on missing id by design). The 422 path is
    structurally unreachable (no body). The meaningful rejection surface
    here is auth: anonymous DELETE must return 401.
    """
    # First verify the authenticated idempotent ack (200 even on missing id).
    auth_resp = authenticated_client.delete("/api/v2/models/favorites/mod_does_not_exist")
    assert auth_resp.status_code == 200, (
        f"Idempotent delete must return 200; got {auth_resp.status_code}"
    )
    # Anonymous rejection surface (401).
    client = authenticated_client._inner
    anon_resp = client.delete("/api/v2/models/favorites/mod_does_not_exist")
    assert anon_resp.status_code == 401, (
        f"Anonymous DELETE favorites must 401; got {anon_resp.status_code}"
    )


def test_delete_models_reviews_returns_404_for_nonexistent_id(authenticated_client):
    """SC3 (cell #23, owner=PLAN_05): DELETE /api/v2/models/reviews/{review_id} -> 404.

    Reclassified from 422 to 404: ``delete_review_as_owner``
    (app/api/v2/routes/profiles/reviews.py:207) takes only a path id and no
    Pydantic-validated body.
    """
    resp = authenticated_client.delete("/api/v2/models/reviews/rev_does_not_exist")
    assert resp.status_code == 404


def test_patch_models_returns_rejection(authenticated_client):
    """SC3 (cell #24, owner=PLAN_05): PATCH /api/v2/models/{model_id} -> rejection (404/422).

    ``update_my_model`` at app/api/v2/routes/models/my_models.py:197 takes an
    Optional-field body schema. A wrong-type list-payload value triggers
    Pydantic 422; if all body fields coerce, the handler raises 404 on the
    missing id. Both are valid rejection paths.
    """
    resp = authenticated_client.patch(
        "/api/v2/models/mod_does_not_exist",
        json={"is_active": ["not", "a", "bool"]},
    )
    assert resp.status_code in (404, 422), (
        f"PATCH model must reject; got {resp.status_code} {resp.text[:200]}"
    )


def test_delete_models_returns_404_for_nonexistent_id(authenticated_client):
    """SC3 (cell #25, owner=PLAN_05): DELETE /api/v2/models/{model_id} -> 404.

    Reclassified from 422 to 404: ``delete_my_model``
    (app/api/v2/routes/models/my_models.py:232) takes only a path id and no
    Pydantic-validated body.
    """
    resp = authenticated_client.delete("/api/v2/models/mod_does_not_exist")
    assert resp.status_code == 404


def test_patch_organizations_profile_returns_rejection(authenticated_client):
    """SC3 (cell #26, owner=PLAN_05): PATCH org profile -> rejection (403/422).

    ``update_organization_profile`` at app/api/v2/routes/profiles/organizations.py:107
    is gated by a role/owner check. Default test_user is not the org owner ->
    403. If the gate is bypassed, a wrong-typed body field triggers 422. Both
    are legitimate rejection paths. Plan 02 reclassified an analogous cell
    to 403 (SUMMARY 12.4-02 cell #17).
    """
    resp = authenticated_client.patch(
        "/api/v2/organizations/profile",
        json={"name": ["not", "a", "string"]},
    )
    assert resp.status_code in (403, 422), (
        f"PATCH org profile must reject; got {resp.status_code} {resp.text[:200]}"
    )


def test_put_seller_notification_preferences_returns_422_for_wrong_body_type(authenticated_client):
    """SC3 (cell #27, owner=PLAN_05): PUT seller notification preferences -> 422.

    ``update_notification_preferences`` at app/api/v2/seller.py:501 accepts a
    body schema. A malformed body triggers Pydantic 422.
    """
    resp = authenticated_client.put(
        "/api/v2/seller/notifications/preferences",
        json={"email_on_sale": "not-a-bool"},
    )
    assert resp.status_code == 422


def test_patch_triggers_schedule_returns_422_for_malformed_body(authenticated_client):
    """SC3 (cell #28, owner=PLAN_05): PATCH /api/v2/triggers/{trigger_id}/schedule -> 422.

    ``update_trigger_schedule`` at app/api/v2/schedules.py:155 accepts a body
    schema. A malformed body triggers Pydantic 422.
    """
    resp = authenticated_client.patch(
        "/api/v2/triggers/trg_does_not_exist/schedule",
        json={"cron_expression": 12345},
    )
    assert resp.status_code == 422


def test_delete_triggers_schedule_returns_404_for_nonexistent_id(authenticated_client):
    """SC3 (cell #29, owner=PLAN_05): DELETE /api/v2/triggers/{trigger_id}/schedule -> 404.

    Reclassified from 422 to 404: ``delete_trigger_schedule``
    (app/api/v2/schedules.py:210) takes only a path id and no
    Pydantic-validated body.
    """
    resp = authenticated_client.delete("/api/v2/triggers/trg_does_not_exist/schedule")
    assert resp.status_code == 404


def test_delete_user_account_returns_rejection_without_confirmation(authenticated_client):
    """SC3 (cell #30, owner=PLAN_05): DELETE /api/v2/user/account -> rejection-path.

    Reclassified from 422 to a generic rejection-path check:
    ``delete_account`` (app/api/v2/gdpr.py:47) takes no Pydantic-validated body
    and no path id. The 422 path is structurally unreachable; the meaningful
    rejection surface is the GDPR confirmation-token mechanism. Without
    confirmation the endpoint must NOT silently succeed. We assert a rejection
    shape: NOT 2xx (no silent delete) AND not 5xx-other-than-503.
    """
    resp = authenticated_client.delete("/api/v2/user/account")
    assert resp.status_code not in (200, 204), (
        f"Account-delete must require confirmation; got {resp.status_code}"
    )
    assert resp.status_code < 500 or resp.status_code == 503, (
        f"Account-delete rejection surface absent: {resp.status_code} {resp.text[:200]}"
    )


def test_patch_users_profile_returns_422_for_wrong_body_type(authenticated_client):
    """SC3 (cell #31, owner=PLAN_05): PATCH /api/v2/users/profile -> 422.

    ``update_user_profile`` at app/api/v2/routes/profiles/users.py:130 accepts
    ``UpdateUserProfileRequest`` (app/schemas/profile.py:101). The
    ``is_public_profile: bool | None`` field is strict-typed; sending a
    list-of-str triggers Pydantic 422.
    """
    resp = authenticated_client.patch(
        "/api/v2/users/profile",
        json={"is_public_profile": ["not", "a", "bool"]},
    )
    assert resp.status_code == 422


def test_patch_workspaces_returns_rejection(authenticated_client):
    """SC3 (cell #32, owner=PLAN_05): PATCH workspace -> rejection (403/404/422).

    ``update_workspace`` at app/api/v2/routes/workspaces/workspaces.py:215 is
    gated by a workspace-member role check. Default test_user has no
    workspace membership -> 403. Otherwise: missing id -> 404; malformed
    body -> 422. All three are legitimate rejection paths.
    """
    resp = authenticated_client.patch(
        "/api/v2/workspaces/ws_does_not_exist",
        json={"name": ["not", "a", "string"]},
    )
    assert resp.status_code in (403, 404, 422), (
        f"PATCH workspace must reject; got {resp.status_code} {resp.text[:200]}"
    )


def test_delete_workspaces_returns_rejection(authenticated_client):
    """SC3 (cell #33, owner=PLAN_05): DELETE workspace -> rejection (403/404).

    Triple reclassification: 422 -> 404 -> {403, 404}. ``delete_workspace``
    (app/api/v2/routes/workspaces/workspaces.py:258) is gated by a
    workspace-member role check that fires before the id lookup. Default
    test_user has no workspace membership -> 403. If gate bypassed, missing
    id -> 404. Both are legitimate rejection paths.
    """
    resp = authenticated_client.delete("/api/v2/workspaces/ws_does_not_exist")
    assert resp.status_code in (403, 404), (
        f"DELETE workspace must reject; got {resp.status_code} {resp.text[:200]}"
    )
