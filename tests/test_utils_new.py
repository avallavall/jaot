"""Tests for new utility functions."""


class TestSlugUtils:
    """Tests for slug utilities."""

    def test_slugify_basic(self):
        from app.shared.utils.slug import slugify

        assert slugify("Hello World") == "hello-world"
        assert slugify("Test 123") == "test-123"
        assert slugify("UPPERCASE") == "uppercase"

    def test_slugify_special_chars(self):
        from app.shared.utils.slug import slugify

        assert slugify("Hello, World!") == "hello-world"
        assert slugify("Test@#$%") == "test"
        assert slugify("a & b") == "a-b"

    def test_slugify_unicode(self):
        from app.shared.utils.slug import slugify

        assert slugify("Café") == "cafe"
        assert slugify("Résumé") == "resume"
        assert slugify("Ñoño") == "nono"

    def test_slugify_whitespace(self):
        from app.shared.utils.slug import slugify

        assert slugify("  spaces  ") == "spaces"
        assert slugify("multiple   spaces") == "multiple-spaces"
        assert slugify("tabs\there") == "tabs-here"

    def test_slugify_max_length(self):
        from app.shared.utils.slug import slugify

        long_text = "a" * 200
        result = slugify(long_text, max_length=50)
        assert len(result) <= 50

    def test_slugify_empty(self):
        from app.shared.utils.slug import slugify

        assert slugify("") == ""
        assert slugify("   ") == ""

    def test_generate_unique_slug(self):
        from app.shared.utils.slug import generate_unique_slug

        existing = ["my-model", "my-model-2"]
        result = generate_unique_slug("My Model", existing)
        assert result == "my-model-3"

    def test_generate_unique_slug_no_conflict(self):
        from app.shared.utils.slug import generate_unique_slug

        existing = ["other-model"]
        result = generate_unique_slug("My Model", existing)
        assert result == "my-model"

    def test_is_valid_slug(self):
        from app.shared.utils.slug import is_valid_slug

        assert is_valid_slug("hello-world") is True
        assert is_valid_slug("test123") is True
        assert is_valid_slug("a-b-c") is True

        assert is_valid_slug("") is False
        assert is_valid_slug("Hello") is False  # uppercase
        assert is_valid_slug("-start") is False  # starts with hyphen
        assert is_valid_slug("end-") is False  # ends with hyphen
        assert is_valid_slug("double--hyphen") is False


class TestResponseUtils:
    """Tests for response utilities."""

    def test_success_response_default(self):
        from app.shared.utils.responses import success_response

        result = success_response()
        assert result["success"] is True
        assert "message" in result

    def test_success_response_custom(self):
        from app.shared.utils.responses import success_response

        result = success_response("Created", data={"id": "123"})
        assert result["success"] is True
        assert result["message"] == "Created"
        assert result["data"]["id"] == "123"

    def test_error_response(self):
        from app.shared.utils.responses import error_response

        result = error_response("Not found", detail="User not found", code="USER_NOT_FOUND")
        assert result["success"] is False
        assert result["error"] == "Not found"
        assert result["detail"] == "User not found"
        assert result["code"] == "USER_NOT_FOUND"

    def test_deleted_response(self):
        from app.shared.utils.responses import deleted_response

        result = deleted_response("User", id="user_123")
        assert result["success"] is True
        assert "deleted" in result["message"].lower()
        assert result["id"] == "user_123"

    def test_created_response(self):
        from app.shared.utils.responses import created_response

        result = created_response("Model", "model_123", extra_field="value")
        assert result["success"] is True
        assert result["id"] == "model_123"
        assert result["extra_field"] == "value"
