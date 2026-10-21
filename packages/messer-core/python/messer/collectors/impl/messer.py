from typing import Any

# `override` was introduced in Python 3.12; use `typing_extensions` for compatibility with older versions
try:
    from typing import override
except ImportError:
    from typing_extensions import override

import structlog

from ...types.events.approval import ApprovalEvent as MesserApprovalEvent
from ...types.events.base import BaseEvent as MesserBaseEvent
from ...types.events.delta import DeltaEvent as MesserDeltaEvent
from ...types.events.interaction import InteractionEvent as MesserInteractionEvent
from ...types.events.output import OutputEvent as MesserOutputEvent
from ...types.events.start import StartEvent as MesserStartEvent
from .. import register_collector
from ..base import BaseCollector

logger = structlog.get_logger("messer.collectors.impl.messer")


@register_collector
class MesserCollector(BaseCollector):
    """Collector for Messer events."""

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self._output_event: MesserOutputEvent | None = None
        # Capture every approval gate that fires during the stream so callers
        # of .collect() can react to all pending approvals — not just the
        # first one — when concurrent runnables (parallel workflow steps,
        # multiplexed tools) gate on the same iteration.
        self._pending_approvals: list[dict[str, Any]] = []
        # Same idea for suspend()-based interactions (ask_user, confirm, ...):
        # capture every InteractionEvent so .collect() callers can enumerate
        # all pending interactions, not just the first.
        self._pending_interactions: list[dict[str, Any]] = []

    @classmethod
    @override
    def can_handle(cls, event: Any) -> bool:
        return isinstance(event, MesserBaseEvent)

    @override
    def process(self, event: MesserBaseEvent) -> MesserBaseEvent | None:
        """Processes Messer events."""
        if isinstance(event, MesserStartEvent):
            return event
        elif isinstance(event, MesserDeltaEvent):
            return event
        elif isinstance(event, MesserApprovalEvent):
            self._pending_approvals.append({
                "approval_id": event.approval_id,
                "runnable_path": event.runnable_path,
                "runnable_name": event.runnable_name,
                "runnable_type": event.runnable_type,
                "tool_call_id": event.tool_call_id,
                "input": event.input,
                "input_schema": event.input_schema,
                "prompt": event.prompt,
                "description": event.description,
                "kind": event.kind,
                "ui": event.ui,
                "grant_key": event.grant_key,
                "grantable": event.grantable,
                "metadata": event.metadata,
                "t0": event.t0,
                "call_id": event.call_id,
                "parent_call_id": event.parent_call_id,
            })
            return event
        elif isinstance(event, MesserInteractionEvent):
            self._pending_interactions.append({
                "interaction_id": event.interaction_id,
                "kind": event.kind,
                "runnable_path": event.runnable_path,
                "runnable_name": event.runnable_name,
                "runnable_type": event.runnable_type,
                "tool_call_id": event.tool_call_id,
                "payload": event.payload,
                "response_schema": event.response_schema,
                "t0": event.t0,
                "call_id": event.call_id,
                "parent_call_id": event.parent_call_id,
            })
            return event
        elif isinstance(event, MesserOutputEvent):
            self._output_event = event
            return event
        elif isinstance(event, MesserBaseEvent):
            return event
        else:
            logger.warning("Unknown Messer event type", event_type=type(event), event=event)

    @override
    def result(self) -> Any:
        """Returns the final OutputEvent enriched with pending gates.

        When concurrent runnables pause, the OutputEvent only references the
        *first* one through ``status``/``output``. We attach the full lists
        under ``metadata['pending_approvals']`` and
        ``metadata['pending_interactions']`` so consumers driving the resume
        loop can see every gate/suspension from one ``.collect()`` call.
        """
        if self._output_event is not None and (self._pending_approvals or self._pending_interactions):
            extra: dict[str, Any] = {}
            if self._pending_approvals:
                extra["pending_approvals"] = list(self._pending_approvals)
            if self._pending_interactions:
                extra["pending_interactions"] = list(self._pending_interactions)
            self._output_event.metadata = {**(self._output_event.metadata or {}), **extra}
        return self._output_event
