"""Dev-only trace log. Off unless DEBUG_RETAIN_TRACES=true, so by default no
user text is ever stored (spec rule 6)."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from ..config import ROOT

DB_PATH = ROOT / "var" / "traces.db"
SCHEMA = Path(__file__).with_name("schema.sql")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    return con


def save(resp, stages, req) -> None:
    with _connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO traces VALUES (?, ?, ?, ?, ?, ?, ?)",
            (resp.request_id, time.time(), req.mode, req.destination, req.text,
             resp.model_dump_json(), json.dumps([s.model_dump() for s in stages])),
        )
