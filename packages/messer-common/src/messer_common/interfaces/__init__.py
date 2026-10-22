"""Interfaces: the spec of generated apps, dashboards and public chats (``interfaces/<slug>/interface.json``).

* :mod:`.spec`       — pydantic models and the exported JSON Schema (for the Composer and the editor)
* :mod:`.validation` — ``validate_interface(json) -> InterfaceSpec`` with precise, located errors
* :mod:`.resolve`    — bindings → SQL parameters, workflow inputs and agent prompts (never SQL text)
* :mod:`.examples`   — templates and documented examples
"""

from __future__ import annotations

from .examples import EXAMPLES, TEMPLATES, TemplateInfo, build_template, template_info
from .resolve import BindingInputError, RequestContext
from .spec import (
    COMPONENT_TYPES,
    GRID_COLUMNS,
    SPEC_VERSION,
    AgentBinding,
    AnyComponent,
    ApprovalsBinding,
    InterfaceSpec,
    KnowledgeSearchBinding,
    KnowledgeSqlBinding,
    StaticBinding,
    WorkflowBinding,
    json_schema,
)
from .validation import InterfaceValidationError, ValidationIssue, check_interface, validate_interface

INTERFACES_DIR = "interfaces"
INTERFACE_FILE = "interface.json"


def interface_path(slug: str) -> str:
    """Repository path of an interface definition."""
    return f"{INTERFACES_DIR}/{slug}/{INTERFACE_FILE}"


__all__ = [
    "COMPONENT_TYPES",
    "EXAMPLES",
    "GRID_COLUMNS",
    "INTERFACES_DIR",
    "INTERFACE_FILE",
    "SPEC_VERSION",
    "TEMPLATES",
    "AgentBinding",
    "AnyComponent",
    "ApprovalsBinding",
    "BindingInputError",
    "InterfaceSpec",
    "InterfaceValidationError",
    "KnowledgeSearchBinding",
    "KnowledgeSqlBinding",
    "RequestContext",
    "StaticBinding",
    "TemplateInfo",
    "ValidationIssue",
    "WorkflowBinding",
    "build_template",
    "check_interface",
    "interface_path",
    "json_schema",
    "template_info",
    "validate_interface",
]
