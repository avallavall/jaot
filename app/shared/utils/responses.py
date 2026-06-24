"""Standard API response helpers."""

from typing import Any


def success_response(
    message: str = "Operation completed successfully",
    data: dict[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Create a standard success response.

    Args:
        message: Success message
        data: Optional data to include
        **kwargs: Additional fields to include

    Returns:
        Success response dict

    Examples:
        >>> success_response()
        {'success': True, 'message': 'Operation completed successfully'}
        >>> success_response("Created", data={"id": "123"})
        {'success': True, 'message': 'Created', 'data': {'id': '123'}}
    """
    response = {"success": True, "message": message}
    if data is not None:
        response["data"] = data
    response.update(kwargs)
    return response


def error_response(
    error: str,
    detail: str | None = None,
    code: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Create a standard error response.

    Args:
        error: Error message
        detail: Optional detailed error info
        code: Optional error code
        **kwargs: Additional fields to include

    Returns:
        Error response dict

    Examples:
        >>> error_response("Not found")
        {'success': False, 'error': 'Not found'}
        >>> error_response("Validation failed", detail="Email is invalid", code="INVALID_EMAIL")
        {'success': False, 'error': 'Validation failed', 'detail': 'Email is invalid', 'code': 'INVALID_EMAIL'}
    """
    response = {"success": False, "error": error}
    if detail is not None:
        response["detail"] = detail
    if code is not None:
        response["code"] = code
    response.update(kwargs)
    return response


def deleted_response(resource: str = "Resource", id: str | None = None) -> dict[str, Any]:
    """Create a standard deletion response.

    Args:
        resource: Name of deleted resource
        id: Optional ID of deleted resource

    Returns:
        Deletion response dict
    """
    response = {"success": True, "message": f"{resource} deleted successfully"}
    if id is not None:
        response["id"] = id
    return response


def updated_response(
    resource: str = "Resource", id: str | None = None, **changes: Any
) -> dict[str, Any]:
    """Create a standard update response.

    Args:
        resource: Name of updated resource
        id: Optional ID of updated resource
        **changes: Changed fields to include

    Returns:
        Update response dict
    """
    response = {"success": True, "message": f"{resource} updated successfully"}
    if id is not None:
        response["id"] = id
    if changes:
        response["changes"] = changes
    return response


def created_response(resource: str, id: str, **extra: Any) -> dict[str, Any]:
    """Create a standard creation response.

    Args:
        resource: Name of created resource
        id: ID of created resource
        **extra: Additional fields to include

    Returns:
        Creation response dict
    """
    response = {
        "success": True,
        "message": f"{resource} created successfully",
        "id": id,
    }
    response.update(extra)
    return response
