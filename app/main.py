import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agent import MigrationAgent
from . import target_api

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_PATH = os.path.join(BASE_DIR, "sample_data", "target_schema.yaml")
SAMPLE_FILES = [
    os.path.join(BASE_DIR, "sample_data", "hr_export.csv"),
    os.path.join(BASE_DIR, "sample_data", "crm_export.csv"),
]

app = FastAPI(title="FDE Migration Agent")
agent = MigrationAgent(SCHEMA_PATH)
push_results: dict[str, dict] = {}


class ResolveBody(BaseModel):
    decision: str  # approve | correct | reject
    value: str | None = None


@app.post("/api/run")
def run_agent():
    """Ingest sample files, map, clean, validate. Idempotent-ish: resets state."""
    global agent
    agent = MigrationAgent(SCHEMA_PATH)
    df = agent.ingest(SAMPLE_FILES)
    agent.clean_and_validate(df)
    return {"ok": True}


@app.get("/api/log")
def get_log():
    return agent.log


@app.get("/api/escalations")
def get_escalations():
    return agent.escalations


@app.post("/api/escalations/{escalation_id}/resolve")
def resolve(escalation_id: str, body: ResolveBody):
    try:
        esc = agent.resolve_escalation(escalation_id, body.decision, body.value)
    except ValueError:
        raise HTTPException(404, "escalation not found")

    if body.decision in ("approve", "correct") and esc["type"] == "cleanup":
        val = body.value if body.decision == "correct" else esc["raw_value"]
        agent._emit(f"Row {esc['row_index']} field '{esc['field']}' resolved to '{val}' by human")

    return esc


@app.get("/api/records")
def get_records():
    return agent.records


@app.get("/api/audit")
def get_audit():
    return agent.audit


@app.post("/api/push")
def push_all():
    results = []
    pending_escalations = [e for e in agent.escalations if e["status"] == "pending"]
    if pending_escalations:
        raise HTTPException(400, f"{len(pending_escalations)} escalations still pending — resolve before pushing")

    for emp_id, record in agent.records.items():
        result = target_api.push_record(record)
        push_results[emp_id] = result
        agent.audit.append({
            "ts": agent.log[-1]["ts"] if agent.log else "",
            "action": "push",
            "employee_id": emp_id,
            "detail": result,
        })
        agent._emit(f"Push {emp_id}: {result['status']}" + (f" ({result.get('reason')})" if result.get("reason") else ""))
        results.append(result)
    return results


@app.post("/api/push/{employee_id}/retry")
def retry_push(employee_id: str):
    record = agent.records.get(employee_id)
    if not record:
        raise HTTPException(404, "record not found")
    fixed = dict(record)
    if fixed.get("manager_id") == "ZZZZ":
        fixed["manager_id"] = None
    result = target_api.push_record(fixed)
    push_results[employee_id] = result
    agent.audit.append({"ts": "", "action": "retry", "employee_id": employee_id, "detail": result})
    agent._emit(f"Retry {employee_id}: {result['status']}")
    return result


@app.post("/api/push/{employee_id}/rollback")
def rollback_push(employee_id: str):
    result = target_api.rollback_record(employee_id)
    push_results.pop(employee_id, None)
    agent.audit.append({"ts": "", "action": "rollback", "employee_id": employee_id, "detail": result})
    agent._emit(f"Rollback {employee_id}: {result['status']}")
    return result


@app.get("/api/push_results")
def get_push_results():
    return push_results


app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")
