-- NEW SUPABASE STAGING PROJECT ONLY. Run manually as the project administrator.
-- Intentionally fails on existing roles; review rather than overwriting role configuration.
BEGIN;
CREATE ROLE intervella_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE ROLE intervella_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE ROLE intervella_student_auth LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE ROLE intervella_ingestor LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE ROLE intervella_auth_admin LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
GRANT CONNECT ON DATABASE postgres TO intervella_migrator, intervella_reader,
  intervella_student_auth, intervella_ingestor, intervella_auth_admin;
GRANT CREATE ON DATABASE postgres TO intervella_migrator;
GRANT USAGE, CREATE ON SCHEMA public TO intervella_migrator;
COMMIT;
-- Set each password interactively with psql \password; never store passwords in this file.
