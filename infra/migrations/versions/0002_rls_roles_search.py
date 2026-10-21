"""Roles, row level security policies, grants, knowledge search functions.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-21

The policy table below is frozen at migration time (later changes get their own migration).
Writes marked "system" have no policy for the application role: they happen on the owner
connection. Every policy relies on helper functions in the messer schema, which read the
transaction-local settings set by rls_session (app.user_id, app.org_id, app.superadmin).
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.engine import make_url

from messer_common.settings import get_settings

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, read_role, write_role, delete_role) — roles: owner > admin > builder > viewer; "system" = no app policy.
POLICIES: list[tuple[str, str, str, str]] = [
    ("alarms", "viewer", "admin", "admin"),
    ("api_keys", "builder", "admin", "admin"),
    ("approvals", "viewer", "builder", "builder"),
    ("budgets", "viewer", "admin", "admin"),
    ("channels", "viewer", "builder", "builder"),
    ("composer_sessions", "viewer", "builder", "builder"),
    ("connections", "viewer", "builder", "admin"),
    ("connector_agents", "viewer", "admin", "admin"),
    ("conversations", "viewer", "builder", "builder"),
    ("credit_ledger", "viewer", "system", "system"),
    ("custom_metrics", "viewer", "admin", "admin"),
    ("data_requests", "admin", "admin", "admin"),
    ("deployments", "viewer", "builder", "builder"),
    ("environments", "viewer", "builder", "builder"),
    ("eval_runs", "viewer", "builder", "builder"),
    ("feedback", "viewer", "viewer", "viewer"),
    ("guard_playbooks", "viewer", "builder", "builder"),
    ("interfaces", "viewer", "builder", "builder"),
    ("invitations", "admin", "admin", "admin"),
    ("invoices", "owner", "system", "system"),
    ("kb_backups", "viewer", "admin", "admin"),
    ("kb_chunks", "viewer", "builder", "builder"),
    ("kb_entities", "viewer", "builder", "builder"),
    ("kb_files", "viewer", "builder", "builder"),
    ("kb_policies", "viewer", "admin", "admin"),
    ("kb_tables", "viewer", "builder", "builder"),
    ("knowledge_bases", "viewer", "builder", "admin"),
    ("memberships", "viewer", "admin", "admin"),
    ("model_policies", "viewer", "admin", "admin"),
    ("projects", "viewer", "builder", "admin"),
    ("runs", "viewer", "builder", "builder"),
    ("scim_tokens", "admin", "admin", "admin"),
    ("secrets", "builder", "builder", "builder"),
    ("spans", "viewer", "builder", "builder"),
    ("sso_connections", "admin", "admin", "admin"),
    ("sso_group_mappings", "admin", "admin", "admin"),
    ("subscriptions", "viewer", "system", "system"),
    ("syncs", "viewer", "builder", "builder"),
    ("triggers", "viewer", "builder", "builder"),
    ("versions", "viewer", "builder", "builder"),
    ("workforce", "viewer", "builder", "builder"),
]

GLOBAL_READ_TABLES = ["plans", "model_prices", "templates", "connectors", "feature_flags"]
SYSTEM_ONLY_TABLES = [
    "auth_credentials",
    "auth_sessions",
    "one_time_tokens",
    "stripe_events",
    "contact_requests",
    "service_health",
]


def _role_password(url: str) -> tuple[str, str]:
    parsed = make_url(url)
    if not parsed.username or not parsed.password:
        raise RuntimeError(f"Database URL must include username and password: {parsed.render_as_string()}")
    return parsed.username, parsed.password


def _q(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    settings = get_settings()
    app_user, app_pw = _role_password(settings.database_app_url)
    ro_user, ro_pw = _role_password(settings.database_readonly_url)

    # ------------------------------------------------------------------ roles
    for user, pw in ((app_user, app_pw), (ro_user, ro_pw)):
        op.execute(
            f"""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = {_q(user)}) THEN
                CREATE ROLE "{user}" LOGIN PASSWORD {_q(pw)} NOBYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE;
              END IF;
            END $$;
            """
        )
    op.execute(f'GRANT "{app_user}" TO CURRENT_USER')  # lets the owner SET ROLE in tests and tooling
    op.execute("CREATE SCHEMA IF NOT EXISTS messer")
    op.execute(f'GRANT USAGE ON SCHEMA messer TO "{app_user}", "{ro_user}"')
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{app_user}", "{ro_user}"')

    # ------------------------------------------------------------------ helper functions
    op.execute(
        """
        CREATE OR REPLACE FUNCTION messer.uid() RETURNS uuid LANGUAGE sql STABLE AS $$
          SELECT nullif(current_setting('app.user_id', true), '')::uuid
        $$;
        CREATE OR REPLACE FUNCTION messer.active_org() RETURNS uuid LANGUAGE sql STABLE AS $$
          SELECT nullif(current_setting('app.org_id', true), '')::uuid
        $$;
        CREATE OR REPLACE FUNCTION messer.is_superadmin() RETURNS boolean LANGUAGE sql STABLE AS $$
          SELECT coalesce(current_setting('app.superadmin', true), 'off') = 'on'
        $$;
        CREATE OR REPLACE FUNCTION messer.role_rank(r text) RETURNS int LANGUAGE sql IMMUTABLE AS $$
          SELECT CASE r WHEN 'owner' THEN 4 WHEN 'admin' THEN 3 WHEN 'builder' THEN 2 WHEN 'viewer' THEN 1 ELSE 0 END
        $$;
        CREATE OR REPLACE FUNCTION messer.org_role(org uuid) RETURNS text
          LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
          SELECT role FROM public.memberships WHERE org_id = org AND user_id = messer.uid()
        $$;
        CREATE OR REPLACE FUNCTION messer.has_role(org uuid, min_role text) RETURNS boolean
          LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
          SELECT messer.is_superadmin()
              OR coalesce(messer.role_rank(messer.org_role(org)), 0) >= messer.role_rank(min_role)
        $$;
        CREATE OR REPLACE FUNCTION messer.shares_org(other uuid) RETURNS boolean
          LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
          SELECT EXISTS (
            SELECT 1 FROM public.memberships a JOIN public.memberships b ON a.org_id = b.org_id
            WHERE a.user_id = messer.uid() AND b.user_id = other
          )
        $$;
        """
    )

    # ------------------------------------------------------------------ policies
    for table, read, write, delete in POLICIES:
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

    # orgs: members read, admins update; creation and deletion run on the owner connection.
    op.execute("ALTER TABLE public.orgs ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY orgs_select ON public.orgs FOR SELECT TO \"{app_user}\" USING (messer.has_role(id, 'viewer'))"
    )
    op.execute(
        f'CREATE POLICY orgs_update ON public.orgs FOR UPDATE TO "{app_user}" '
        "USING (messer.has_role(id, 'admin')) WITH CHECK (messer.has_role(id, 'admin'))"
    )
    # users: yourself and people you share an organization with.
    op.execute("ALTER TABLE public.users ENABLE ROW LEVEL SECURITY")
    op.execute(
        f'CREATE POLICY users_select ON public.users FOR SELECT TO "{app_user}" '
        "USING (id = messer.uid() OR messer.shares_org(id) OR messer.is_superadmin())"
    )
    op.execute(
        f'CREATE POLICY users_update ON public.users FOR UPDATE TO "{app_user}" '
        "USING (id = messer.uid()) WITH CHECK (id = messer.uid())"
    )
    # audit_log: insert-only. Members insert for their org; admins read.
    op.execute("ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY")
    op.execute(
        f'CREATE POLICY audit_insert ON public.audit_log FOR INSERT TO "{app_user}" '
        "WITH CHECK ((org_id IS NULL AND actor_id = messer.uid()) OR messer.has_role(org_id, 'viewer'))"
    )
    op.execute(
        f'CREATE POLICY audit_select ON public.audit_log FOR SELECT TO "{app_user}" '
        "USING (messer.has_role(org_id, 'admin'))"
    )
    # notifications: each user sees and marks only their own.
    op.execute("ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY")
    op.execute(
        f'CREATE POLICY notifications_select ON public.notifications FOR SELECT TO "{app_user}" '
        "USING (user_id = messer.uid() AND messer.has_role(org_id, 'viewer'))"
    )
    op.execute(
        f'CREATE POLICY notifications_update ON public.notifications FOR UPDATE TO "{app_user}" '
        "USING (user_id = messer.uid()) WITH CHECK (user_id = messer.uid())"
    )
    # Global catalogs: readable by everyone, writable only on the owner connection.
    for table in GLOBAL_READ_TABLES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'CREATE POLICY "{table}_read" ON public."{table}" FOR SELECT TO "{app_user}" USING (true)')
    # Auth internals: RLS on, no policy → invisible to the application role.
    for table in SYSTEM_ONLY_TABLES:
        op.execute(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY')

    # ------------------------------------------------------------------ grants
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO "{app_user}"')
    op.execute(f'REVOKE UPDATE, DELETE, TRUNCATE ON public.audit_log FROM "{app_user}"')
    op.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO "{app_user}"')
    op.execute(
        f'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{app_user}"'
    )

    # ------------------------------------------------------------------ full-text search
    op.execute(
        """
        CREATE OR REPLACE FUNCTION messer.kb_tsv(heading text, body text) RETURNS tsvector
          LANGUAGE sql STABLE AS $$
          SELECT setweight(to_tsvector('spanish', unaccent(coalesce(heading, ''))), 'A')
              || setweight(to_tsvector('english', unaccent(coalesce(heading, ''))), 'A')
              || setweight(to_tsvector('spanish', unaccent(coalesce(body, ''))), 'B')
              || setweight(to_tsvector('english', unaccent(coalesce(body, ''))), 'B')
        $$;
        CREATE OR REPLACE FUNCTION messer.kb_tsquery(q text) RETURNS tsquery LANGUAGE sql STABLE AS $$
          SELECT websearch_to_tsquery('spanish', unaccent(q)) || websearch_to_tsquery('english', unaccent(q))
        $$;
        CREATE OR REPLACE FUNCTION messer.kb_chunks_tsv_trigger() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          NEW.tsv := messer.kb_tsv(NEW.heading, NEW.content);
          RETURN NEW;
        END $$;
        CREATE TRIGGER kb_chunks_tsv BEFORE INSERT OR UPDATE OF content, heading ON public.kb_chunks
          FOR EACH ROW EXECUTE FUNCTION messer.kb_chunks_tsv_trigger();
        """
    )

    # ------------------------------------------------------------------ knowledge search functions
    # Access: the caller must be able to read the KB's org (RLS identity), or the session must be scoped to
    # exactly this KB (app.kb_scope, set by the read-only SQL console and the agent SQL tool).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION messer.can_read_kb(p_kb uuid) RETURNS boolean
          LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
          SELECT coalesce(current_setting('app.kb_scope', true), '') = p_kb::text
              OR EXISTS (SELECT 1 FROM public.knowledge_bases kb WHERE kb.id = p_kb AND messer.has_role(kb.org_id, 'viewer'))
        $$;

        CREATE OR REPLACE FUNCTION public.kb_vector_search(p_kb uuid, p_embedding vector, p_k int DEFAULT 10)
          RETURNS TABLE(chunk_id uuid, file_id uuid, filename text, content text, heading text,
                        page_from int, page_to int, score double precision, metadata jsonb)
          LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $$
        BEGIN
          IF NOT messer.can_read_kb(p_kb) THEN RAISE EXCEPTION 'knowledge base not accessible' USING ERRCODE = '42501'; END IF;
          RETURN QUERY
            SELECT c.id, c.file_id, f.filename, c.content, c.heading, c.page_from, c.page_to,
                   (1 - (c.embedding <=> p_embedding))::double precision AS score, c.metadata
            FROM public.kb_chunks c JOIN public.kb_files f ON f.id = c.file_id
            WHERE c.kb_id = p_kb AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> p_embedding
            LIMIT least(greatest(p_k, 1), 200);
        END $$;

        CREATE OR REPLACE FUNCTION public.kb_text_search(p_kb uuid, p_query text, p_k int DEFAULT 10)
          RETURNS TABLE(chunk_id uuid, file_id uuid, filename text, content text, heading text,
                        page_from int, page_to int, score double precision, metadata jsonb)
          LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $$
        DECLARE q tsquery := messer.kb_tsquery(p_query);
        BEGIN
          IF NOT messer.can_read_kb(p_kb) THEN RAISE EXCEPTION 'knowledge base not accessible' USING ERRCODE = '42501'; END IF;
          RETURN QUERY
            SELECT c.id, c.file_id, f.filename, c.content, c.heading, c.page_from, c.page_to,
                   ts_rank_cd(c.tsv, q)::double precision AS score, c.metadata
            FROM public.kb_chunks c JOIN public.kb_files f ON f.id = c.file_id
            WHERE c.kb_id = p_kb AND c.tsv @@ q
            ORDER BY ts_rank_cd(c.tsv, q) DESC
            LIMIT least(greatest(p_k, 1), 200);
        END $$;

        CREATE OR REPLACE FUNCTION public.kb_hybrid_search(p_kb uuid, p_query text, p_embedding vector, p_k int DEFAULT 10)
          RETURNS TABLE(chunk_id uuid, file_id uuid, filename text, content text, heading text,
                        page_from int, page_to int, score double precision, metadata jsonb)
          LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $$
        DECLARE pool int := least(greatest(p_k, 1), 200) * 4;
        BEGIN
          IF NOT messer.can_read_kb(p_kb) THEN RAISE EXCEPTION 'knowledge base not accessible' USING ERRCODE = '42501'; END IF;
          RETURN QUERY
            WITH v AS (
              SELECT c.id, row_number() OVER (ORDER BY c.embedding <=> p_embedding) AS r
              FROM public.kb_chunks c WHERE c.kb_id = p_kb AND c.embedding IS NOT NULL
              ORDER BY c.embedding <=> p_embedding LIMIT pool
            ), t AS (
              SELECT c.id, row_number() OVER (ORDER BY ts_rank_cd(c.tsv, messer.kb_tsquery(p_query)) DESC) AS r
              FROM public.kb_chunks c WHERE c.kb_id = p_kb AND c.tsv @@ messer.kb_tsquery(p_query)
              ORDER BY ts_rank_cd(c.tsv, messer.kb_tsquery(p_query)) DESC LIMIT pool
            ), fused AS (
              -- Reciprocal Rank Fusion (k = 60)
              SELECT coalesce(v.id, t.id) AS id,
                     coalesce(1.0 / (60 + v.r), 0) + coalesce(1.0 / (60 + t.r), 0) AS s
              FROM v FULL OUTER JOIN t ON v.id = t.id
            )
            SELECT c.id, c.file_id, f.filename, c.content, c.heading, c.page_from, c.page_to,
                   fused.s::double precision, c.metadata
            FROM fused JOIN public.kb_chunks c ON c.id = fused.id JOIN public.kb_files f ON f.id = c.file_id
            ORDER BY fused.s DESC
            LIMIT least(greatest(p_k, 1), 200);
        END $$;
        """
    )
    for fn in (
        "kb_vector_search(uuid, vector, int)",
        "kb_text_search(uuid, text, int)",
        "kb_hybrid_search(uuid, text, vector, int)",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION public.{fn} FROM PUBLIC")
        op.execute(f'GRANT EXECUTE ON FUNCTION public.{fn} TO "{app_user}", "{ro_user}"')
    op.execute(f'GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA messer TO "{app_user}", "{ro_user}"')


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS public.kb_hybrid_search(uuid, text, vector, int)")
    op.execute("DROP FUNCTION IF EXISTS public.kb_text_search(uuid, text, int)")
    op.execute("DROP FUNCTION IF EXISTS public.kb_vector_search(uuid, vector, int)")
    op.execute("DROP TRIGGER IF EXISTS kb_chunks_tsv ON public.kb_chunks")
    for table, *_ in POLICIES:
        op.execute(f'ALTER TABLE public."{table}" DISABLE ROW LEVEL SECURITY')
    op.execute("DROP SCHEMA IF EXISTS messer CASCADE")
