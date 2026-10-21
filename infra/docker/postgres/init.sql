-- Local/compose Postgres bootstrap: owner role, extensions. Application roles are created by migrations.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'messer') THEN
    CREATE ROLE messer LOGIN PASSWORD 'messer' CREATEROLE CREATEDB;
  END IF;
END $$;
SELECT 'CREATE DATABASE messer OWNER messer' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'messer')\gexec
\connect messer
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;
GRANT ALL ON SCHEMA public TO messer;
