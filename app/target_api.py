"""Stub target system. Fails deterministically for a known bad id so the
push/retry/rollback UI has something real to demonstrate."""
import random

_pushed = {}


def push_record(record: dict) -> dict:
    emp_id = record.get("employee_id")
    if not emp_id:
        return {"status": "failure", "employee_id": emp_id, "reason": "missing employee_id"}

    # deterministic failure for demo: manager_id pointing to a non-existent employee
    manager_id = record.get("manager_id")
    if manager_id == "ZZZZ":
        return {"status": "failure", "employee_id": emp_id, "reason": "manager_id ZZZZ not found in target system"}

    if random.random() < 0.05:
        return {"status": "failure", "employee_id": emp_id, "reason": "transient timeout"}

    _pushed[emp_id] = record
    return {"status": "success", "employee_id": emp_id}


def rollback_record(emp_id: str) -> dict:
    if emp_id in _pushed:
        del _pushed[emp_id]
        return {"status": "rolled_back", "employee_id": emp_id}
    return {"status": "not_found", "employee_id": emp_id}


def get_pushed() -> dict:
    return dict(_pushed)
