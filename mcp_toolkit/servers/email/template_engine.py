"""Jinja2-inspired email template engine with variable injection."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EmailTemplate:
    """An email template with subject and body."""

    name: str
    subject: str
    body: str
    variables: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.variables:
            self.variables = self._extract_variables()

    def _extract_variables(self) -> list[str]:
        """Extract {{variable_name}} placeholders from subject and body."""
        pattern = r"\{\{(\w+)\}\}"
        found = set(re.findall(pattern, self.subject))
        found.update(re.findall(pattern, self.body))
        return sorted(found)

    def render(self, variables: dict[str, Any]) -> tuple[str, str]:
        """Render the template with provided variables.

        Returns (rendered_subject, rendered_body).
        """
        subject = self.subject
        body = self.body
        for key, value in variables.items():
            placeholder = "{{" + key + "}}"
            subject = subject.replace(placeholder, str(value))
            body = body.replace(placeholder, str(value))
        return subject, body

    def validate(self, variables: dict[str, Any]) -> list[str]:
        """Check for missing required variables. Returns list of missing var names."""
        return [v for v in self.variables if v not in variables]


class TemplateEngine:
    """Manages a registry of email templates."""

    def __init__(self) -> None:
        self._templates: dict[str, EmailTemplate] = {}

    def register(self, template: EmailTemplate) -> None:
        self._templates[template.name] = template

    def get(self, name: str) -> EmailTemplate | None:
        return self._templates.get(name)

    def list_templates(self) -> list[EmailTemplate]:
        return list(self._templates.values())

    def render(self, name: str, variables: dict[str, Any]) -> tuple[str, str]:
        """Render a named template. Raises KeyError if not found."""
        template = self._templates.get(name)
        if not template:
            raise KeyError(f"Template '{name}' not found")
        return template.render(variables)

    @property
    def count(self) -> int:
        return len(self._templates)
