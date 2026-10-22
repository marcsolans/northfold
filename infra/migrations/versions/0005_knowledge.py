"""Phase 4 knowledge bases.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-21

* ``messer_kb_reader``: NOLOGIN group role granted to every per-knowledge-base reader role
  (``kb_<hex>_reader``). It only holds EXECUTE on the ``kb_*_search`` functions, so a reader can
  call them (access is still checked by ``messer.can_read_kb``) but cannot read any public table.
* ``messer_readonly`` becomes NOINHERIT: it is a member of every reader role but must switch to one
  explicitly (``SET LOCAL ROLE``), so it never holds the union of all knowledge bases' privileges.
* Unique keys for connector files (``kb_id, external_id``) and entity suggestions (``kb_id, match_key``).
* ``messer.kb_try_*`` conversion helpers (Spanish and English number/date formats) used when a table
  column changes type; they return NULL instead of failing.
* ``kb_vector_search`` / ``kb_hybrid_search`` are redefined to cast the untyped embedding column to the
  knowledge base's dimension, so each knowledge base's partial HNSW index
  (``ix_kb_chunks_vec_<hex>`` on ``(embedding::vector(dim)) WHERE kb_id = ...``) is used.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.engine import make_url

from messer_common.settings import get_settings

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KB_GROUP_ROLE = "messer_kb_reader"
SEARCH_FUNCTIONS = (
    "kb_vector_search(uuid, vector, int)",
    "kb_text_search(uuid, text, int)",
    "kb_hybrid_search(uuid, text, vector, int)",
)


def _readonly_user() -> str:
    parsed = make_url(get_settings().database_readonly_url)
    if not parsed.username:
        raise RuntimeError("DATABASE_READONLY_URL must include a username")
    return parsed.username


def upgrade() -> None:
    ro_user = _readonly_user()

    # ------------------------------------------------------------------ roles
    op.execute(
        f"""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{KB_GROUP_ROLE}') THEN
            CREATE ROLE "{KB_GROUP_ROLE}" NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE;
          END IF;
        END $$;
        """
    )
    op.execute(
        f"""
        DO $$ BEGIN
          ALTER ROLE "{ro_user}" NOINHERIT;
        EXCEPTION WHEN insufficient_privilege THEN
          RAISE NOTICE 'could not set NOINHERIT on {ro_user}; reader grants use INHERIT FALSE instead';
        END $$;
        """
    )
    op.execute(f'GRANT USAGE ON SCHEMA public TO "{KB_GROUP_ROLE}"')

    # ------------------------------------------------------------------ unique keys
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_kb_files_kb_external ON public.kb_files (kb_id, external_id) "
        "WHERE external_id IS NOT NULL"
    )
    op.execute("ALTER TABLE public.kb_entities ADD CONSTRAINT uq_kb_entities_kb_match_key UNIQUE (kb_id, match_key)")

    # ------------------------------------------------------------------ conversion helpers
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION messer.kb_try_numeric(v text) RETURNS numeric
          LANGUAGE plpgsql IMMUTABLE AS $$
        DECLARE s text := btrim(coalesce(v, ''));
        BEGIN
          s := replace(replace(s, ' ', ''), chr(160), '');
          s := regexp_replace(s, '^[€$£]|[€$£%]$', '', 'g');
          IF s = '' THEN RETURN NULL; END IF;
          IF s ~ '^[+-]?\d{1,3}(\.\d{3}){2,}(,\d+)?$' OR s ~ '^[+-]?\d{1,3}(\.\d{3})+,\d+$' THEN
            s := replace(replace(s, '.', ''), ',', '.');
          ELSIF s ~ '^[+-]?\d{1,3}(,\d{3}){2,}(\.\d+)?$' OR s ~ '^[+-]?\d{1,3}(,\d{3})+\.\d+$' THEN
            s := replace(s, ',', '');
          ELSIF s ~ '^[+-]?\d+,\d+$' THEN
            s := replace(s, ',', '.');
          END IF;
          IF s !~ '^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$' THEN RETURN NULL; END IF;
          RETURN s::numeric;
        EXCEPTION WHEN others THEN RETURN NULL;
        END $$;

        CREATE OR REPLACE FUNCTION messer.kb_try_bigint(v text) RETURNS bigint
          LANGUAGE plpgsql IMMUTABLE AS $$
        DECLARE n numeric := messer.kb_try_numeric(v);
        BEGIN
          IF n IS NULL OR n <> trunc(n) THEN RETURN NULL; END IF;
          RETURN n::bigint;
        EXCEPTION WHEN others THEN RETURN NULL;
        END $$;

        CREATE OR REPLACE FUNCTION messer.kb_try_bool(v text) RETURNS boolean
          LANGUAGE sql IMMUTABLE AS $$
          SELECT CASE lower(btrim(coalesce(v, '')))
            WHEN 'true' THEN true WHEN 't' THEN true WHEN 'yes' THEN true WHEN 'y' THEN true
            WHEN 'si' THEN true WHEN 'sí' THEN true WHEN 's' THEN true WHEN 'verdadero' THEN true WHEN '1' THEN true
            WHEN 'false' THEN false WHEN 'f' THEN false WHEN 'no' THEN false WHEN 'n' THEN false
            WHEN 'falso' THEN false WHEN '0' THEN false
            ELSE NULL END
        $$;

        CREATE OR REPLACE FUNCTION messer.kb_try_timestamptz(v text) RETURNS timestamptz
          LANGUAGE plpgsql STABLE AS $$
        DECLARE s text := btrim(coalesce(v, ''));
        DECLARE m text[];
        BEGIN
          IF s = '' THEN RETURN NULL; END IF;
          IF s ~ '^\d{4}-\d{2}-\d{2}([T ]\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?)?(Z|[+-]\d{2}(:?\d{2})?)?$' THEN
            IF s ~ '(Z|[+-]\d{2}(:?\d{2})?)$' AND s ~ '[T ]' THEN
              RETURN s::timestamptz;
            END IF;
            RETURN (s::timestamp) AT TIME ZONE 'UTC';
          END IF;
          m := regexp_match(s, '^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$');
          IF m IS NOT NULL THEN
            RETURN make_timestamptz(m[3]::int, m[2]::int, m[1]::int,
                                    coalesce(m[4], '0')::int, coalesce(m[5], '0')::int,
                                    coalesce(m[6], '0')::double precision, 'UTC');
          END IF;
          RETURN NULL;
        EXCEPTION WHEN others THEN RETURN NULL;
        END $$;

        CREATE OR REPLACE FUNCTION messer.kb_try_date(v text) RETURNS date
          LANGUAGE plpgsql STABLE AS $$
        DECLARE s text := btrim(coalesce(v, ''));
        DECLARE m text[];
        BEGIN
          IF s = '' THEN RETURN NULL; END IF;
          IF s ~ '^\d{4}-\d{2}-\d{2}$' THEN RETURN s::date; END IF;
          m := regexp_match(s, '^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$');
          IF m IS NOT NULL THEN RETURN make_date(m[3]::int, m[2]::int, m[1]::int); END IF;
          RETURN (messer.kb_try_timestamptz(s) AT TIME ZONE 'UTC')::date;
        EXCEPTION WHEN others THEN RETURN NULL;
        END $$;

        CREATE OR REPLACE FUNCTION messer.kb_try_jsonb(v text) RETURNS jsonb
          LANGUAGE plpgsql IMMUTABLE AS $$
        BEGIN
          IF v IS NULL OR btrim(v) = '' THEN RETURN NULL; END IF;
          RETURN v::jsonb;
        EXCEPTION WHEN others THEN RETURN NULL;
        END $$;
        """
    )

    # ------------------------------------------------------------------ dimension-aware search functions
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.kb_vector_search(p_kb uuid, p_embedding vector, p_k int DEFAULT 10)
          RETURNS TABLE(chunk_id uuid, file_id uuid, filename text, content text, heading text,
                        page_from int, page_to int, score double precision, metadata jsonb)
          LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $$
        DECLARE dim int;
        DECLARE lim int := least(greatest(p_k, 1), 200);
        BEGIN
          IF NOT messer.can_read_kb(p_kb) THEN
            RAISE EXCEPTION 'knowledge base not accessible' USING ERRCODE = '42501';
          END IF;
          SELECT kb.embedding_dim INTO dim FROM public.knowledge_bases kb WHERE kb.id = p_kb;
          IF dim IS NULL THEN RETURN; END IF;
          IF vector_dims(p_embedding) <> dim THEN
            RAISE EXCEPTION 'embedding has % dimensions, the knowledge base uses %', vector_dims(p_embedding), dim
              USING ERRCODE = '22000';
          END IF;
          PERFORM set_config('hnsw.ef_search', greatest(40, least(lim * 2, 1000))::text, true);
          RETURN QUERY EXECUTE format(
            'SELECT c.id, c.file_id, f.filename, c.content, c.heading, c.page_from, c.page_to,
                    (1 - ((c.embedding::vector(%1$s)) <=> $1::vector(%1$s)))::double precision, c.metadata
             FROM public.kb_chunks c JOIN public.kb_files f ON f.id = c.file_id
             WHERE c.kb_id = %2$L::uuid AND c.embedding IS NOT NULL
             ORDER BY (c.embedding::vector(%1$s)) <=> $1::vector(%1$s)
             LIMIT $2', dim, p_kb)
          USING p_embedding, lim;
        END $$;

        CREATE OR REPLACE FUNCTION public.kb_hybrid_search(p_kb uuid, p_query text, p_embedding vector, p_k int DEFAULT 10)
          RETURNS TABLE(chunk_id uuid, file_id uuid, filename text, content text, heading text,
                        page_from int, page_to int, score double precision, metadata jsonb)
          LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public AS $$
        DECLARE dim int;
        DECLARE lim int := least(greatest(p_k, 1), 200);
        DECLARE pool int := least(greatest(p_k, 1), 200) * 4;
        DECLARE q tsquery := messer.kb_tsquery(coalesce(p_query, ''));
        BEGIN
          IF NOT messer.can_read_kb(p_kb) THEN
            RAISE EXCEPTION 'knowledge base not accessible' USING ERRCODE = '42501';
          END IF;
          SELECT kb.embedding_dim INTO dim FROM public.knowledge_bases kb WHERE kb.id = p_kb;
          IF dim IS NULL THEN RETURN; END IF;
          IF vector_dims(p_embedding) <> dim THEN
            RAISE EXCEPTION 'embedding has % dimensions, the knowledge base uses %', vector_dims(p_embedding), dim
              USING ERRCODE = '22000';
          END IF;
          PERFORM set_config('hnsw.ef_search', greatest(40, least(pool, 1000))::text, true);
          RETURN QUERY EXECUTE format(
            'WITH v AS (
               SELECT c.id, row_number() OVER (ORDER BY (c.embedding::vector(%1$s)) <=> $1::vector(%1$s)) AS r
               FROM (
                 SELECT c0.id, c0.embedding FROM public.kb_chunks c0
                 WHERE c0.kb_id = %2$L::uuid AND c0.embedding IS NOT NULL
                 ORDER BY (c0.embedding::vector(%1$s)) <=> $1::vector(%1$s)
                 LIMIT $3
               ) c
             ), t AS (
               SELECT c.id, row_number() OVER (ORDER BY ts_rank_cd(c.tsv, $2) DESC) AS r
               FROM public.kb_chunks c
               WHERE c.kb_id = %2$L::uuid AND c.tsv @@ $2
               ORDER BY ts_rank_cd(c.tsv, $2) DESC
               LIMIT $3
             ), fused AS (
               SELECT coalesce(v.id, t.id) AS id,
                      coalesce(1.0 / (60 + v.r), 0) + coalesce(1.0 / (60 + t.r), 0) AS s
               FROM v FULL OUTER JOIN t ON v.id = t.id
             )
             SELECT c.id, c.file_id, f.filename, c.content, c.heading, c.page_from, c.page_to,
                    fused.s::double precision, c.metadata
             FROM fused JOIN public.kb_chunks c ON c.id = fused.id JOIN public.kb_files f ON f.id = c.file_id
             ORDER BY fused.s DESC, c.id
             LIMIT $4', dim, p_kb)
          USING p_embedding, q, pool, lim;
        END $$;
        """
    )
    for fn in SEARCH_FUNCTIONS:
        op.execute(f'GRANT EXECUTE ON FUNCTION public.{fn} TO "{KB_GROUP_ROLE}"')


def downgrade() -> None:
    for fn in SEARCH_FUNCTIONS:
        op.execute(f'REVOKE EXECUTE ON FUNCTION public.{fn} FROM "{KB_GROUP_ROLE}"')
    # Restore the dimension-agnostic definitions from 0002.
    op.execute(
        """
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
    for name in ("kb_try_jsonb", "kb_try_date", "kb_try_timestamptz", "kb_try_bool", "kb_try_bigint", "kb_try_numeric"):
        op.execute(f"DROP FUNCTION IF EXISTS messer.{name}(text)")
    op.execute("ALTER TABLE public.kb_entities DROP CONSTRAINT IF EXISTS uq_kb_entities_kb_match_key")
    op.execute("DROP INDEX IF EXISTS public.uq_kb_files_kb_external")
