"""
Template Engine

Transforms user-friendly input into OptimizationProblem format using templates.

A template defines:
1. Input fields (what the user sees)
2. Problem template (how to build the optimization problem)

Dynamic templates specify a "generator" type and optional "generator_params".
The engine dispatches to the appropriate generator from the registry.

Example template for "Budget Allocation":
{
    "generator": "budget_allocation",
    "generator_params": {},
    "input_fields": [
        {"name": "total_budget", "type": "number", "label": "Total Budget"},
        {"name": "departments", "type": "array", "label": "Departments"}
    ]
}
"""

import re
from typing import Any

from app.domains.solver.services.generators import get_generator
from app.schemas.optimization import OptimizationProblem


class TemplateEngine:
    """Transform user input through templates into OptimizationProblem format.

    Uses the generator registry for dynamic problem generation.
    Keeps static template rendering for legacy/simple templates.
    """

    def __init__(self) -> None:
        pass

    def render(
        self,
        template: dict[str, Any],
        user_input: dict[str, Any],
    ) -> OptimizationProblem:
        """
        Render a template with user input to create an OptimizationProblem.

        Args:
            template: Template definition (YAML or DB catalog)
            user_input: User-provided input data

        Returns:
            OptimizationProblem ready for solving
        """
        # Dynamic template: dispatch via generator registry
        if "generator" in template:
            generator_type = template.get("generator", "generic")
            generator_params = template.get("generator_params", {})
            generator = get_generator(generator_type)
            return generator.generate(user_input, generator_params)

        # Static template: variable substitution
        problem_template = template.get("problem_template", {})
        return self._render_static_template(problem_template, user_input)

    def _render_static_template(
        self,
        template: dict[str, Any],
        context: dict[str, Any],
    ) -> OptimizationProblem:
        """Render a static template with variable substitution."""
        rendered = self._substitute_recursive(template, context)
        return OptimizationProblem(**rendered)

    def _substitute_recursive(
        self,
        obj: Any,
        context: dict[str, Any],
    ) -> Any:
        """Recursively substitute {{variable}} placeholders."""
        if isinstance(obj, str):
            return self._substitute_string(obj, context)
        if isinstance(obj, dict):
            return {k: self._substitute_recursive(v, context) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._substitute_recursive(item, context) for item in obj]
        return obj

    def _substitute_string(self, s: str, context: dict[str, Any]) -> Any:
        """Substitute {{variable}} in a string."""
        match = re.fullmatch(r"\{\{(\w+(?:\.\w+)*)\}\}", s.strip())
        if match:
            return self._get_nested_value(context, match.group(1))

        def replace(m: re.Match[str]) -> str:
            value = self._get_nested_value(context, m.group(1))
            return str(value) if value is not None else m.group(0)

        return re.sub(r"\{\{(\w+(?:\.\w+)*)\}\}", replace, s)

    def _get_nested_value(self, context: dict[str, Any], path: str) -> Any:
        """Get a nested value from context using dot notation."""
        parts = path.split(".")
        value: Any = context
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
            if value is None:
                return None
        return value

    def _sanitize_name(self, name: str) -> str:
        """Sanitize a name to be a valid variable identifier.

        Kept for backward compatibility. Delegates to the same logic
        used by BaseGenerator.sanitize_name.
        """
        sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", str(name))
        if sanitized and sanitized[0].isdigit():
            sanitized = f"v_{sanitized}"
        return sanitized.lower()


# Singleton
_template_engine: TemplateEngine | None = None


def get_template_engine() -> TemplateEngine:
    """Get or create template engine singleton."""
    global _template_engine
    if _template_engine is None:
        _template_engine = TemplateEngine()
    return _template_engine
