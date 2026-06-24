"""Simplified tests for pagination functionality."""

from app.shared.utils.pagination import create_paginated_response


class TestPaginationHelpers:
    """Test pagination utility functions."""

    def test_create_paginated_response_first_page(self):
        """Test creating paginated response for first page."""
        items = [{"id": i} for i in range(20)]
        total = 100
        page = 1
        page_size = 20

        result = create_paginated_response(items, total, page, page_size)

        assert result["items"] == items
        assert result["total"] == 100
        assert result["page"] == 1
        assert result["page_size"] == 20
        assert result["total_pages"] == 5
        assert result["has_next"] is True
        assert result["has_prev"] is False

    def test_create_paginated_response_middle_page(self):
        """Test creating paginated response for middle page."""
        items = [{"id": i} for i in range(20)]
        total = 100
        page = 3
        page_size = 20

        result = create_paginated_response(items, total, page, page_size)

        assert result["page"] == 3
        assert result["total_pages"] == 5
        assert result["has_next"] is True
        assert result["has_prev"] is True

    def test_create_paginated_response_last_page(self):
        """Test creating paginated response for last page."""
        items = [{"id": i} for i in range(20)]
        total = 100
        page = 5
        page_size = 20

        result = create_paginated_response(items, total, page, page_size)

        assert result["page"] == 5
        assert result["total_pages"] == 5
        assert result["has_next"] is False
        assert result["has_prev"] is True

    def test_create_paginated_response_partial_last_page(self):
        """Test paginated response when last page is not full."""
        items = [{"id": i} for i in range(7)]
        total = 47
        page = 3
        page_size = 20

        result = create_paginated_response(items, total, page, page_size)

        assert len(result["items"]) == 7
        assert result["total"] == 47
        assert result["total_pages"] == 3
        assert result["has_next"] is False
        assert result["has_prev"] is True

    def test_create_paginated_response_single_page(self):
        """Test paginated response when all items fit in one page."""
        items = [{"id": i} for i in range(10)]
        total = 10
        page = 1
        page_size = 20

        result = create_paginated_response(items, total, page, page_size)

        assert result["total_pages"] == 1
        assert result["has_next"] is False
        assert result["has_prev"] is False

    def test_create_paginated_response_empty(self):
        """Test paginated response with no items."""
        items = []
        total = 0
        page = 1
        page_size = 20

        result = create_paginated_response(items, total, page, page_size)

        assert result["items"] == []
        assert result["total"] == 0
        assert result["total_pages"] == 0
        assert result["has_next"] is False
        assert result["has_prev"] is False
