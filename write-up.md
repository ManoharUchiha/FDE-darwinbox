# Approach

The agent runs a fixed pipeline — ingest, map, clean, validate, dedupe —
then stops for review only where it's genuinely unsure, and finally pushes
to the mock target system once the queue is clear.

**Mapping.** Each source column is scored against every target field using
string similarity against the field name plus a small alias list (e.g.
`hire_date` also matches "joining date", "doj", "start date"). The agent
applies the top match automatically.

**Cleanup.** Dates, casing/whitespace, status vocabulary, and email
formatting are normalized with deterministic rules (multiple date formats
tried in order, `.title()` casing, a status synonym map). Exact-duplicate
employee IDs across files are dropped, keeping the first occurrence, with
the drop written to the audit trail.

## Where I drew the escalation line

The rule I used: **escalate only when a wrong automatic decision would be
hard to detect later, not just because a value looked untidy.**

Concretely, three triggers:

1. **Ambiguous mapping** — top two candidate target fields score within
   0.08 of each other. A messy header that's still clearly closest to one
   field gets mapped silently; a header that could plausibly mean two
   different things does not.
2. **Required field still missing after a second cleaning attempt** — an
   empty required field (name, email) is a case the agent cannot fabricate
   an answer for, so it escalates rather than guessing or silently dropping
   the record.
3. **A value the agent can't clean with confidence** — an unparseable date,
   a status string with no synonym match, a foreign key that doesn't
   resolve to a known ID. These are "I don't know what this means," not
   "this is technically imperfect."

Everything else — whitespace, casing, recognized date formats, exact
duplicates, empty *optional* fields — is handled and applied without a
human in the loop, because a wrong guess there is either harmless or fully
recoverable (it's visible in the audit trail and correctable after the
fact).

In the sample run (10 raw rows, 2 files): the agent silently maps 15/15
columns, cleans and validates 7 records, drops 2 duplicates on its own, and
escalates exactly 2 cases — a row missing both name and email that it
cannot invent. Everything else goes through untouched by a human, which is
the point: review effort scales with actual ambiguity, not with row count.

## What I'd build next

- Replace the string-similarity mapper with an LLM call for the ambiguous
  cases only (cheap, since most columns never reach that path), and use it
  to explain *why* a column is ambiguous in plain language for the
  non-technical reviewer.
- Persist state to a real datastore instead of in-memory, so a run survives
  a server restart and supports concurrent migrations.
- Batch/streaming ingestion for larger files instead of loading everything
  with pandas at once.
- Field-level rollback (undo one corrected value) instead of only
  record-level rollback against the target system.
