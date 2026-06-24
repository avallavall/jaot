"""Slug generation utilities."""

import re
import unicodedata


def slugify(text: str, max_length: int = 100) -> str:
    """Convert text to URL-friendly slug.

    Args:
        text: Text to convert
        max_length: Maximum length of slug

    Returns:
        URL-friendly slug (lowercase, hyphens, no special chars)

    Examples:
        >>> slugify("Hello World!")
        'hello-world'
        >>> slugify("Café & Résumé")
        'cafe-resume'
        >>> slugify("  Multiple   Spaces  ")
        'multiple-spaces'
    """
    if not text:
        return ""

    # Normalize unicode characters (é -> e, ñ -> n, etc.)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")

    # Convert to lowercase
    text = text.lower()

    # Replace spaces and underscores with hyphens
    text = re.sub(r"[\s_]+", "-", text)

    text = re.sub(r"[^a-z0-9-]", "", text)

    text = re.sub(r"-+", "-", text)

    text = text.strip("-")

    # Truncate to max length (at word boundary if possible)
    if len(text) > max_length:
        text = text[:max_length].rsplit("-", 1)[0]

    return text


def generate_unique_slug(base_text: str, existing_slugs: list[str], max_length: int = 100) -> str:
    """Generate a unique slug by appending numbers if needed.

    Args:
        base_text: Text to convert to slug
        existing_slugs: List of existing slugs to avoid
        max_length: Maximum length of slug

    Returns:
        Unique slug

    Examples:
        >>> generate_unique_slug("My Model", ["my-model"])
        'my-model-2'
        >>> generate_unique_slug("My Model", ["my-model", "my-model-2"])
        'my-model-3'
    """
    base_slug = slugify(base_text, max_length - 4)  # Reserve space for "-999"

    if base_slug not in existing_slugs:
        return base_slug

    counter = 2
    while f"{base_slug}-{counter}" in existing_slugs:
        counter += 1
        if counter > 999:
            # Fallback: use random suffix
            import secrets

            return f"{base_slug}-{secrets.token_hex(3)}"

    return f"{base_slug}-{counter}"


def is_valid_slug(slug: str) -> bool:
    """Check if string is a valid slug.

    Args:
        slug: String to validate

    Returns:
        True if valid slug format
    """
    if not slug:
        return False

    # Must be lowercase alphanumeric with hyphens
    # Cannot start or end with hyphen
    # Cannot have consecutive hyphens
    pattern = r"^[a-z0-9]+(-[a-z0-9]+)*$"
    return bool(re.match(pattern, slug))
