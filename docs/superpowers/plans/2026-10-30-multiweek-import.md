# Multiweek importer implementation plan

Goal: drop several authorized HTML exports, resolve genuine evidence gaps, review
coverage once, stage independent weeks, and explicitly publish an atomic selection.

Architecture: retain strict parsers, inventory profiles, immutable dataset payloads,
and the serialized ingestion pipeline. Add nonoverlapping active periods and daily
source timestamps. Keep the singleton pointer as the publication concurrency token
and compatibility identifier, not as the complete set of active schedules.

Constraints: static review only. No tests, builds, lint, formatting, type checks,
servers, dependency installation, deployment, or actual intranet ingestion. No
automatic publication, guessed year, capture timestamp, inventory or free coverage.

- [x] Add migration 0004: active periods, daily source freshness, legacy backfill,
  restricted grants, and overlap/published-parent constraints.
- [x] Extend existing publication transaction to publish one or several candidates,
  replace exact matching periods only, compare freshness against the replaced
  sources, retain history, and preserve the union of active room identities.
- [x] Route availability, room search, room/day and building/day queries through
  active periods, with exact coverage unions and source-aware metadata.
- [x] Discover daily dates and weekly caption periods using explicit year evidence;
  group into Sunday weeks without mixing competing sources. Surface missing,
  malformed, ambiguous, duplicate and overlapping sources independently.
- [x] Add server-enforced eligible coverage review to existing manifest endpoint,
  preserving mappings, capacities, provenance, profile versions and input hashes.
- [x] Add a compact private multiweek queue using existing upload/review/stage
  routes and an explicit atomic publication endpoint; retain the legacy editor.
- [x] Add regression cases without executing them. Review changed callers, grants,
  migration rollback, DST, timestamp regression and publication concurrency by
  reading only. Document rollout and untested limitations.

Review focus: ambiguous year across December/January; missing capture evidence;
malformed/truncated grids; incomplete daily weeks; same-date competing sources;
partial period overlaps; equal capture times with different content; stale lookahead
sources; cross-period gaps; concurrent publication/profile changes; legacy seeds.
