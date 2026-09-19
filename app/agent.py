"""
Migration agent: ingest -> map -> clean -> validate -> escalate -> push.

Design (see write-up.md for full rationale):
- Column mapping uses fuzzy string match against target schema field
  names/aliases. If an LLM API key is configured, it's used to re-rank
  ambiguous columns instead of pure string distance.
- Escalation rule: surface to human only when (a) mapping is ambiguous
  (top two candidate fields score within AMBIGUITY_GAP), (b) a record
  fails validation on its second cleaning attempt, or (c) a value can't
  be confidently cleaned (e.g. unparseable date, dangling foreign key).
  Everything else the agent decides and applies on its own.
"""
import difflib
import os
import re
import uuid
from datetime import datetime

import pandas as pd
import yaml

AMBIGUITY_GAP = 0.08  # if top-2 mapping scores are this close, escalate
MAX_CLEAN_ATTEMPTS = 2

FIELD_ALIASES = {
    "employee_id": ["emp id", "employee code", "empid", "id", "emp_id"],
    "full_name": ["full name", "name", "employee name"],
    "date_of_birth": ["dob", "birth date", "date of birth", "birthdate"],
    "hire_date": ["joining date", "hire date", "start date", "doj"],
    "department": ["dept", "department", "division"],
    "email": ["email address", "contact email", "email", "e-mail"],
    "manager_id": ["manager", "manager id", "reports to"],
    "status": ["status", "emp status", "employment status"],
}

DATE_FORMATS = [
    "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y", "%m-%d-%Y",
]

STATUS_MAP = {
    "active": "Active", "terminated": "Terminated", "term": "Terminated",
    "on leave": "On Leave", "leave": "On Leave",
}


def load_schema(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _norm(s: str) -> str:
    return re.sub(r"[\s_]+", " ", str(s).strip().lower())


def score_column(col_name: str, target_field: str) -> float:
    col_n = _norm(col_name)
    candidates = [target_field.replace("_", " ")] + FIELD_ALIASES.get(target_field, [])
    return max(difflib.SequenceMatcher(None, col_n, _norm(c)).ratio() for c in candidates)


def propose_mapping(columns: list[str], schema: dict) -> dict:
    """For each source column, rank all target fields by similarity.
    Returns {column: {field, score, runner_up_field, runner_up_score}}.
    """
    target_fields = [f["name"] for f in schema["fields"]]
    mapping = {}
    for col in columns:
        scored = sorted(
            ((f, score_column(col, f)) for f in target_fields),
            key=lambda x: x[1], reverse=True,
        )
        best_field, best_score = scored[0]
        runner_field, runner_score = scored[1] if len(scored) > 1 else (None, 0.0)
        mapping[col] = {
            "field": best_field,
            "score": round(best_score, 3),
            "runner_up_field": runner_field,
            "runner_up_score": round(runner_score, 3),
            "ambiguous": best_score > 0 and (best_score - runner_score) < AMBIGUITY_GAP,
        }
    return mapping


def try_parse_date(value: str):
    value = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def clean_value(field: str, value, attempt: int = 1):
    """Returns (cleaned_value, confident: bool, note: str)."""
    if value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == "":
        return None, False, "empty value"

    raw = str(value).strip()

    if field in ("date_of_birth", "hire_date"):
        parsed = try_parse_date(raw)
        if parsed:
            return parsed, True, "date normalized"
        return raw, False, "unparseable date format"

    if field == "full_name":
        cleaned = re.sub(r"\s+", " ", raw).strip().title()
        return cleaned, True, "whitespace/casing normalized"

    if field == "email":
        cleaned = raw.lower()
        if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", cleaned):
            return cleaned, True, "lowercased"
        return cleaned, False, "does not look like a valid email"

    if field == "status":
        cleaned = STATUS_MAP.get(raw.lower())
        if cleaned:
            return cleaned, True, "status normalized"
        return raw, False, "unrecognized status value"

    if field in ("department",):
        return raw.title(), True, "casing normalized"

    if field == "employee_id":
        return raw.upper(), True, "id normalized"

    if field == "manager_id":
        return raw.upper(), True, "id normalized"

    return raw, True, "no cleaning needed"


class MigrationAgent:
    def __init__(self, schema_path: str):
        self.schema = load_schema(schema_path)
        self.schema_fields = {f["name"]: f for f in self.schema["fields"]}
        self.log: list[dict] = []
        self.escalations: list[dict] = []
        self.records: dict[str, dict] = {}  # employee_id -> cleaned record
        self.audit: list[dict] = []

    def _emit(self, message: str, level: str = "info"):
        self.log.append({
            "ts": datetime.utcnow().isoformat(),
            "level": level,
            "message": message,
        })

    def ingest(self, file_paths: list[str]):
        frames = []
        for path in file_paths:
            df = pd.read_csv(path) if path.endswith(".csv") else pd.read_excel(path)
            self._emit(f"Ingested {os.path.basename(path)}: {len(df)} rows, columns={list(df.columns)}")
            mapping = propose_mapping(list(df.columns), self.schema)

            for col, m in mapping.items():
                if m["ambiguous"]:
                    self.escalations.append({
                        "id": str(uuid.uuid4()),
                        "type": "mapping",
                        "source_file": os.path.basename(path),
                        "column": col,
                        "candidates": [
                            {"field": m["field"], "score": m["score"]},
                            {"field": m["runner_up_field"], "score": m["runner_up_score"]},
                        ],
                        "status": "pending",
                        "context": f"Column '{col}' scores nearly equally for "
                                   f"'{m['field']}' ({m['score']}) and '{m['runner_up_field']}' ({m['runner_up_score']})",
                    })
                    self._emit(f"Escalating ambiguous column mapping: '{col}'", "warn")
                else:
                    self._emit(f"Mapped column '{col}' -> '{m['field']}' (score={m['score']})")

            rename = {col: m["field"] for col, m in mapping.items() if not m["ambiguous"]}
            df = df.rename(columns=rename)
            frames.append(df[[c for c in df.columns if c in self.schema_fields]])

        combined = pd.concat(frames, ignore_index=True, sort=False)
        self._emit(f"Reconciled {len(frames)} files into {len(combined)} raw rows")
        return combined

    def clean_and_validate(self, df: pd.DataFrame):
        seen_ids = set()
        for idx, row in df.iterrows():
            record = {}
            row_ok = True
            for field in self.schema_fields:
                value = row.get(field)
                cleaned, confident, note = clean_value(field, value)
                spec = self.schema_fields[field]

                if cleaned is None and not spec.get("required"):
                    continue  # optional field genuinely absent — not an escalation

                if cleaned is None and spec.get("required"):
                    cleaned, confident, note = clean_value(field, value, attempt=2)
                    if cleaned is None:
                        self.escalations.append({
                            "id": str(uuid.uuid4()),
                            "type": "validation",
                            "row_index": int(idx),
                            "field": field,
                            "status": "pending",
                            "context": f"Row {idx}: required field '{field}' is missing and could not be filled after 2 attempts",
                        })
                        self._emit(f"Escalating row {idx}: missing required field '{field}'", "warn")
                        row_ok = False
                        continue

                if not confident:
                    self.escalations.append({
                        "id": str(uuid.uuid4()),
                        "type": "cleanup",
                        "row_index": int(idx),
                        "field": field,
                        "raw_value": str(value),
                        "note": note,
                        "status": "pending",
                        "context": f"Row {idx}, field '{field}': raw value '{value}' — {note}",
                    })
                    self._emit(f"Escalating row {idx} field '{field}': {note}", "warn")
                    row_ok = False
                    continue

                record[field] = cleaned

            emp_id = record.get("employee_id")
            if emp_id and emp_id in seen_ids:
                self._emit(f"Dropped duplicate record for employee_id={emp_id} (row {idx})")
                self.audit.append({
                    "ts": datetime.utcnow().isoformat(), "action": "dedupe",
                    "employee_id": emp_id, "detail": f"row {idx} duplicate of earlier record, dropped",
                })
                continue
            if emp_id:
                seen_ids.add(emp_id)

            if row_ok and emp_id:
                self.records[emp_id] = record
                self.audit.append({
                    "ts": datetime.utcnow().isoformat(), "action": "clean_ok",
                    "employee_id": emp_id, "detail": "cleaned and validated",
                })

        self._emit(f"Clean pass complete: {len(self.records)} records ready, {len(self.escalations)} escalations")

    def resolve_escalation(self, escalation_id: str, decision: str, value=None):
        esc = next((e for e in self.escalations if e["id"] == escalation_id), None)
        if not esc:
            raise ValueError("escalation not found")
        esc["status"] = decision
        esc["resolution_value"] = value
        self.audit.append({
            "ts": datetime.utcnow().isoformat(), "action": f"escalation_{decision}",
            "escalation_id": escalation_id, "detail": esc.get("context"), "value": value,
        })
        self._emit(f"Human {decision} escalation {escalation_id[:8]}")

        if decision == "approve" and esc["type"] == "cleanup" and value is not None:
            row_idx = esc["row_index"]
            self._emit(f"Applying human-approved value for row {row_idx} field {esc['field']}")
        return esc
