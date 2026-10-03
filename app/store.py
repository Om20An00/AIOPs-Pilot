"""Persist investigations in PostgreSQL (one row per incident, JSONB payload)."""
import json
import time

import psycopg

from app.config import DATABASE_URL


def init(retries: int = 30):
    for i in range(retries):
        try:
            with psycopg.connect(DATABASE_URL, autocommit=True) as c:
                c.execute("""CREATE TABLE IF NOT EXISTS investigations (
                    incident_id TEXT PRIMARY KEY, status TEXT NOT NULL, result JSONB NOT NULL,
                    updated_at TIMESTAMPTZ DEFAULT now())""")
            return
        except psycopg.OperationalError:
            if i == retries - 1:
                raise
            time.sleep(1)


def save(incident_id: str, status: str, result: dict):
    with psycopg.connect(DATABASE_URL, autocommit=True) as c:
        c.execute("""INSERT INTO investigations (incident_id, status, result) VALUES (%s,%s,%s)
                     ON CONFLICT (incident_id) DO UPDATE SET status=EXCLUDED.status,
                     result=EXCLUDED.result, updated_at=now()""",
                  (incident_id, status, json.dumps(result)))


def get(incident_id: str):
    with psycopg.connect(DATABASE_URL) as c:
        row = c.execute("SELECT result FROM investigations WHERE incident_id=%s", (incident_id,)).fetchone()
    return row[0] if row else None


def statuses() -> dict:
    with psycopg.connect(DATABASE_URL) as c:
        return dict(c.execute("SELECT incident_id, status FROM investigations").fetchall())
