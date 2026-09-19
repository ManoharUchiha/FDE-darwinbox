# Migration Agent — FDE Take-Home

Agent that migrates messy HR/CRM exports into a target employee schema,
with a human-in-the-loop web console.

## Tech stack

- Backend: Python, FastAPI (single process, in-memory state — no DB needed for this scope)
- Data: pandas, PyYAML
- Frontend: static HTML/CSS/vanilla JS (no build step)
- Mock target system: in-process stub (`app/target_api.py`)

## Setup

```bash
cd "FDE app"
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8811
```

Open http://127.0.0.1:8811

## Using it

1. Click **Run Agent** — ingests `sample_data/hr_export.csv` and
   `sample_data/crm_export.csv`, maps columns to `sample_data/target_schema.yaml`,
   cleans values, dedupes, validates.
2. Watch the **Activity Log** for what it did on its own.
3. Resolve anything in the **Escalation Queue** (approve / correct / reject).
4. Once the queue is empty, click **Push to Target** to send records to the
   mock API. One record (`E008`, bad `manager_id`) fails on purpose —
   demonstrate **Retry** (clears the bad reference) or **Rollback** on a
   successful push.
5. **Audit Trail** shows every decision: dedupes, cleanups, escalation
   resolutions, pushes, retries, rollbacks.

## Sample data

Two files, same "employee" entity, deliberately inconsistent:
- Different column names (`Emp ID` vs `EmployeeCode`, `Dept` vs `Division`)
- Mixed date formats (`03/14/1990`, `1988-11-02`, `14/03/1992`)
- A duplicate record (`E001`, `E002` appear in both files)
- Missing required fields (row with blank name/email)
- A dangling foreign key (`manager_id = ZZZZ`, doesn't exist)

Swap in your own files/schema by editing `sample_data/` and `SAMPLE_FILES` /
`SCHEMA_PATH` in `app/main.py`.

## Where the agent draws the escalation line

See `write-up.md`.
