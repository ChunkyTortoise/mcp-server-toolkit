"""Map natural language field names to GoHighLevel custom field IDs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GHLField:
    """A GoHighLevel custom field definition."""

    id: str
    name: str
    field_key: str
    field_type: str = "text"
    options: list[str] | None = None


class GHLFieldMapper:
    """Maps natural language field references to GHL custom field IDs.

    Maintains a registry of known fields and performs fuzzy matching
    to resolve references like "lead source" to the actual GHL field ID.
    """

    def __init__(self) -> None:
        self._fields: dict[str, GHLField] = {}
        self._aliases: dict[str, str] = {}

    def register_field(self, ghl_field: GHLField, aliases: list[str] | None = None) -> None:
        """Register a GHL custom field with optional aliases."""
        self._fields[ghl_field.id] = ghl_field
        key = ghl_field.name.lower().replace(" ", "_")
        self._aliases[key] = ghl_field.id
        self._aliases[ghl_field.field_key.lower()] = ghl_field.id
        for alias in aliases or []:
            self._aliases[alias.lower().replace(" ", "_")] = ghl_field.id

    def resolve(self, field_ref: str) -> GHLField | None:
        """Resolve a natural language field reference to a GHL field."""
        normalized = field_ref.lower().strip().replace(" ", "_")
        field_id = self._aliases.get(normalized)
        if field_id:
            return self._fields.get(field_id)

        # Fuzzy: check if reference is a substring of any alias
        for alias, fid in self._aliases.items():
            if normalized in alias or alias in normalized:
                return self._fields.get(fid)

        return None

    def resolve_dict(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Resolve a dict of {natural_name: value} to {ghl_field_key: value}."""
        resolved = {}
        for name, value in fields.items():
            field = self.resolve(name)
            if field:
                resolved[field.field_key] = value
            else:
                resolved[name] = value
        return resolved

    def list_fields(self) -> list[GHLField]:
        """List all registered fields."""
        return list(self._fields.values())

    @property
    def field_count(self) -> int:
        return len(self._fields)
