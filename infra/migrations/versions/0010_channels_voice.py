"""Phase 8 channels and voice.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-21

Reserved migration slot owned by the channels_voice workstream. Add DDL here; new tables must enable RLS
with policies following the pattern in 0002 (messer.has_role(org_id, ...)).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url

from messer_common.settings import get_settings

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ============================================================================================== channels
# ``channel_messages``: inbound/outbound message log of channels (idempotency per provider message id, delivery
# state). Written on the owner connection only; members read, admins delete.

_CHANNEL_POLICIES: list[tuple[str, str, str, str]] = [
    ("channel_messages", "viewer", "system", "admin"),
]


def _q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _channels_upgrade() -> None:
    app_user = make_url(get_settings().database_app_url).username or "messer_app"
    uuid_t = postgresql.UUID(as_uuid=True)
    op.create_table(
        "channel_messages",
        sa.Column("id", uuid_t, primary_key=True),
        sa.Column("org_id", uuid_t, sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", uuid_t, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", uuid_t, sa.ForeignKey("channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", uuid_t, sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("kind", sa.String(30), nullable=False, server_default="text"),
        sa.Column("sender_id", sa.String(255), nullable=True),
        sa.Column("sender_name", sa.String(255), nullable=True),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("run_id", uuid_t, nullable=True),
        sa.Column("reply_to_id", uuid_t, nullable=True),
        sa.Column("simulated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("channel_id", "direction", "external_id", name="uq_channel_messages_external"),
    )
    op.create_index("ix_channel_messages_org_id", "channel_messages", ["org_id"])
    op.create_index("ix_channel_messages_channel_created", "channel_messages", ["channel_id", "created_at"])
    op.create_index("ix_channel_messages_conversation_created", "channel_messages", ["conversation_id", "created_at"])
    op.create_index("ix_channel_messages_run", "channel_messages", ["run_id"])

    for table, read, write, delete in _CHANNEL_POLICIES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table}_select" ON public."{table}" FOR SELECT TO "{app_user}" '
            f"USING (messer.has_role(org_id, {_q(read)}))"
        )
        if write != "system":
            op.execute(
                f'CREATE POLICY "{table}_insert" ON public."{table}" FOR INSERT TO "{app_user}" '
                f"WITH CHECK (messer.has_role(org_id, {_q(write)}))"
            )
            op.execute(
                f'CREATE POLICY "{table}_update" ON public."{table}" FOR UPDATE TO "{app_user}" '
                f"USING (messer.has_role(org_id, {_q(write)})) WITH CHECK (messer.has_role(org_id, {_q(write)}))"
            )
        if delete != "system":
            op.execute(
                f'CREATE POLICY "{table}_delete" ON public."{table}" FOR DELETE TO "{app_user}" '
                f"USING (messer.has_role(org_id, {_q(delete)}))"
            )


def _channels_downgrade() -> None:
    op.drop_table("channel_messages")


# ================================================================================================= voice
# ``voice_phone_numbers``: Twilio/Telnyx numbers of the deployment's account assigned to a project's agent.
# ``voice_calls``: one row per call (browser, phone, LiveKit) with transcript, per-turn latency, usage, cost and
# recording. Members read, builders write (browser sessions and outbound calls are created by the API on the
# application role; the voice service writes on the owner connection), admins delete.

_VOICE_POLICIES: list[tuple[str, str, str, str]] = [
    ("voice_phone_numbers", "viewer", "builder", "admin"),
    ("voice_calls", "viewer", "builder", "admin"),
]


def _voice_upgrade() -> None:
    app_user = make_url(get_settings().database_app_url).username or "messer_app"
    uuid_t = postgresql.UUID(as_uuid=True)
    jsonb_list = sa.text("'[]'::jsonb")
    jsonb_obj = sa.text("'{}'::jsonb")
    op.create_table(
        "voice_phone_numbers",
        sa.Column("id", uuid_t, primary_key=True),
        sa.Column("org_id", uuid_t, sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", uuid_t, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workforce_name", sa.String(80), nullable=False),
        sa.Column("environment", sa.String(20), nullable=False, server_default="production"),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("number", sa.String(40), nullable=False),
        sa.Column("external_id", sa.String(120), nullable=False, server_default=""),
        sa.Column("label", sa.String(200), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("purchased", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("record_calls", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("greeting", sa.Text(), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", uuid_t, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("provider", "number", name="uq_voice_phone_numbers_provider_number"),
    )
    op.create_index("ix_voice_phone_numbers_org_id", "voice_phone_numbers", ["org_id"])
    op.create_index("ix_voice_phone_numbers_project", "voice_phone_numbers", ["project_id"])

    op.create_table(
        "voice_calls",
        sa.Column("id", uuid_t, primary_key=True),
        sa.Column("org_id", uuid_t, sa.ForeignKey("orgs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", uuid_t, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("workforce_name", sa.String(80), nullable=False),
        sa.Column("environment", sa.String(20), nullable=False, server_default="development"),
        sa.Column("conversation_id", uuid_t, sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column(
            "phone_number_id", uuid_t, sa.ForeignKey("voice_phone_numbers.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("user_id", uuid_t, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("transport", sa.String(20), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False, server_default="voice"),
        sa.Column("mode", sa.String(10), nullable=False, server_default="audio"),
        sa.Column("direction", sa.String(10), nullable=False, server_default="inbound"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("from_number", sa.String(40), nullable=True),
        sa.Column("to_number", sa.String(40), nullable=True),
        sa.Column("external_call_id", sa.String(120), nullable=True),
        sa.Column("language", sa.String(16), nullable=False, server_default="es"),
        sa.Column("stt_provider", sa.String(40), nullable=True),
        sa.Column("tts_provider", sa.String(40), nullable=True),
        sa.Column("record", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("recording_consent", sa.String(20), nullable=True),
        sa.Column("recording_key", sa.Text(), nullable=True),
        sa.Column("recording_ms", sa.BigInteger(), nullable=True),
        sa.Column("transcript", postgresql.JSONB(), nullable=False, server_default=jsonb_list),
        sa.Column("turns", postgresql.JSONB(), nullable=False, server_default=jsonb_list),
        sa.Column("usage", postgresql.JSONB(), nullable=False, server_default=jsonb_obj),
        sa.Column("voice_cost_usd", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("model_cost_usd", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("credits", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("error", postgresql.JSONB(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=jsonb_obj),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_voice_calls_org_id", "voice_calls", ["org_id"])
    op.create_index("ix_voice_calls_project_created", "voice_calls", ["project_id", "created_at"])
    op.create_index("ix_voice_calls_conversation", "voice_calls", ["conversation_id"])
    op.create_index("ix_voice_calls_external", "voice_calls", ["transport", "external_call_id"])

    for table, read, write, delete in _VOICE_POLICIES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY "{table}_select" ON public."{table}" FOR SELECT TO "{app_user}" '
            f"USING (messer.has_role(org_id, {_q(read)}))"
        )
        op.execute(
            f'CREATE POLICY "{table}_insert" ON public."{table}" FOR INSERT TO "{app_user}" '
            f"WITH CHECK (messer.has_role(org_id, {_q(write)}))"
        )
        op.execute(
            f'CREATE POLICY "{table}_update" ON public."{table}" FOR UPDATE TO "{app_user}" '
            f"USING (messer.has_role(org_id, {_q(write)})) WITH CHECK (messer.has_role(org_id, {_q(write)}))"
        )
        op.execute(
            f'CREATE POLICY "{table}_delete" ON public."{table}" FOR DELETE TO "{app_user}" '
            f"USING (messer.has_role(org_id, {_q(delete)}))"
        )


def _voice_downgrade() -> None:
    op.drop_table("voice_calls")
    op.drop_table("voice_phone_numbers")


def upgrade() -> None:
    # channels
    _channels_upgrade()
    # voice
    _voice_upgrade()


def downgrade() -> None:
    # voice
    _voice_downgrade()
    # channels
    _channels_downgrade()
