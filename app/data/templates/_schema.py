"""Pydantic validation models for YAML template definitions.

Each category YAML file contains a list of TemplateDefinition objects that are
validated at load time. Invalid templates produce clear error messages.
"""

import logging
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, field_validator

from app.models.optimization_model import ModelCategory

logger = logging.getLogger(__name__)

# Pre-compute valid category values for the validator
_VALID_CATEGORIES = {m.value for m in ModelCategory}


class TemplateInputField(BaseModel):
    """Schema for a single input field in a template form."""

    name: str
    label: str
    type: Literal["number", "integer", "string", "boolean", "array", "object"]
    description: str = ""
    required: bool = True
    minimum: float | None = None
    maximum: float | None = None
    enum: list[Any] | None = None
    items: dict[str, Any] | None = None
    default: Any = None


class TemplateDefinition(BaseModel):
    """A single optimization template definition, validated from YAML."""

    id: str
    name: str
    display_name: str
    short_description: str
    description: str
    category: str
    tags: list[str] = []
    problem_type_tags: list[str] = []
    generator_type: str
    generator_params: dict[str, Any] = {}
    input_schema: dict[str, Any]
    input_fields: list[TemplateInputField]
    example_input: dict[str, Any]
    scenario_description: str = ""
    is_featured: bool = False
    estimated_variables: int | None = None
    estimated_constraints: int | None = None
    version: str = "1.0.0"

    @field_validator("category")
    @classmethod
    def warn_unknown_category(cls, v: str) -> str:
        if v not in _VALID_CATEGORIES:
            logger.warning(
                "Template category '%s' is not in ModelCategory enum. Valid categories: %s",
                v,
                sorted(_VALID_CATEGORIES),
            )
        return v


class TemplateCategoryFile(BaseModel):
    """Root model for a category YAML file."""

    category: str
    category_display_name: str
    templates: list[TemplateDefinition]


def load_templates_from_yaml(yaml_content: str) -> TemplateCategoryFile:
    """Parse a YAML string into a validated TemplateCategoryFile.

    Raises ``yaml.YAMLError`` for malformed YAML or ``ValidationError`` for
    schema violations.
    """
    data = yaml.safe_load(yaml_content)
    return TemplateCategoryFile(**data)
