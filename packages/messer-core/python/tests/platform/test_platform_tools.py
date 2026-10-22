"""Platform tool helpers: approval gates on plain functions and on tools."""

from messer import Agent, Tool
from messer.core.test_model import TestModel
from messer.platform.tools import calculator, require_approval


def issue_credit_note(invoice: str, amount: float) -> str:
    """Issue a credit note for an invoice."""
    return f"{invoice}:{amount}"


def test_require_approval_wraps_plain_functions() -> None:
    gated = require_approval(issue_credit_note, prompt="Emitir abono")
    assert isinstance(gated, Tool)
    assert gated.requires_approval is True and gated.approval_prompt == "Emitir abono"
    agent = Agent(name="facturas", model=TestModel(), tools=[gated])
    tool = next(t for t in agent.tools if getattr(t, "name", None) == "issue_credit_note")
    assert tool.requires_approval is True  # the agent keeps the same Tool, so the gate survives


def test_require_approval_marks_existing_tools() -> None:
    tool = calculator()
    gated = require_approval(tool)
    assert gated is tool and gated.requires_approval is True
