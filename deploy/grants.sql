-- Run manually as intervella_migrator, AFTER alembic upgrade head on NEW staging.
BEGIN;
REVOKE ALL ON SCHEMA utscvacant, student_auth FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON ALL TABLES IN SCHEMA utscvacant, student_auth FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA utscvacant, student_auth FROM PUBLIC, anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA utscvacant, student_auth
  REVOKE ALL ON TABLES FROM PUBLIC, anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA utscvacant, student_auth
  REVOKE ALL ON SEQUENCES FROM PUBLIC, anon, authenticated, service_role;
GRANT USAGE ON SCHEMA utscvacant TO intervella_reader, intervella_ingestor;
GRANT SELECT ON utscvacant.buildings, utscvacant.rooms, utscvacant.datasets,
  utscvacant.dataset_state, utscvacant.room_coverage, utscvacant.meeting_occurrences TO intervella_reader;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA utscvacant TO intervella_ingestor;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA utscvacant TO intervella_ingestor;
GRANT USAGE ON SCHEMA student_auth TO intervella_student_auth, intervella_auth_admin;
GRANT SELECT, INSERT, UPDATE, DELETE ON student_auth.session, student_auth.attempt TO intervella_student_auth;
GRANT SELECT ON student_auth.control TO intervella_student_auth;
GRANT SELECT, UPDATE ON student_auth.control TO intervella_auth_admin;
GRANT DELETE ON student_auth.session TO intervella_auth_admin;
COMMIT;
