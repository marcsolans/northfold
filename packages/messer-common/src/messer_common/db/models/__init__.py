"""All ORM models. Importing this module registers every table on ``Base.metadata``."""

from .access import (
    ROLES,
    ApiKey,
    AuditLog,
    AuthCredential,
    AuthSession,
    DataRequest,
    Invitation,
    Membership,
    Notification,
    OneTimeToken,
    Org,
    ScimToken,
    SsoConnection,
    SsoGroupMapping,
    User,
)
from .billing import (
    Budget,
    CreditLedger,
    FeatureFlag,
    Invoice,
    ModelPolicy,
    ModelPrice,
    Plan,
    StripeEvent,
    Subscription,
)
from .execution import RUN_STATUSES, Approval, EvalRun, Feedback, GuardPlaybook, Run, Span
from .interfaces import Channel, ContactRequest, Conversation, Interface, ServiceHealth
from .knowledge import (
    Connection,
    Connector,
    ConnectorAgent,
    KbBackup,
    KbChunk,
    KbEntity,
    KbFile,
    KbPolicy,
    KbTable,
    KnowledgeBase,
    Sync,
)
from .projects import (
    Alarm,
    ComposerSession,
    CustomMetric,
    Deployment,
    Environment,
    Project,
    Secret,
    Template,
    Trigger,
    Version,
    Workforce,
)

__all__ = [
    "ROLES",
    "RUN_STATUSES",
    "Alarm",
    "ApiKey",
    "Approval",
    "AuditLog",
    "AuthCredential",
    "AuthSession",
    "Budget",
    "Channel",
    "ComposerSession",
    "Connection",
    "Connector",
    "ConnectorAgent",
    "ContactRequest",
    "Conversation",
    "CreditLedger",
    "CustomMetric",
    "DataRequest",
    "Deployment",
    "Environment",
    "EvalRun",
    "FeatureFlag",
    "Feedback",
    "GuardPlaybook",
    "Interface",
    "Invitation",
    "Invoice",
    "KbBackup",
    "KbChunk",
    "KbEntity",
    "KbFile",
    "KbPolicy",
    "KbTable",
    "KnowledgeBase",
    "Membership",
    "ModelPolicy",
    "ModelPrice",
    "Notification",
    "OneTimeToken",
    "Org",
    "Plan",
    "Project",
    "Run",
    "ScimToken",
    "Secret",
    "ServiceHealth",
    "Span",
    "SsoConnection",
    "SsoGroupMapping",
    "StripeEvent",
    "Subscription",
    "Sync",
    "Template",
    "Trigger",
    "User",
    "Version",
    "Workforce",
]

# Workstream model modules (e.g. ``db/models/billing_extra.py``) are imported automatically so their tables
# register on ``Base.metadata`` (Alembic autogenerate, tests) without editing this file.
import importlib as _importlib
import pkgutil as _pkgutil

_CORE_MODULES = {"access", "billing", "execution", "interfaces", "knowledge", "projects"}
for _info in _pkgutil.iter_modules(__path__):
    if _info.name not in _CORE_MODULES and not _info.name.startswith("_"):
        _importlib.import_module(f"{__name__}.{_info.name}")
