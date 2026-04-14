"""
SQLite-backed persistence layer.

Schema (3 tables):
  projects      – one row per .qgs/.qgz file; stores cumulative total_seconds.
  sessions      – one row per tracked work session; used for history & export.
  active_session– at most ONE row (id=1); written every heartbeat so that
                  QGIS crashes lose at most 5 s of tracking data.

Crash-recovery logic runs in __init__ before any other operation:
  if active_session exists → compute recovered seconds from last_heartbeat,
  update projects.total_seconds, write a completed session row, delete the
  active_session sentinel.

WAL journal mode is set so SQLite never writes partial pages to the main db
file; a hard kill cannot corrupt the database.
"""

import csv
import json
import os
import sqlite3
from datetime import datetime, timezone


# ── helpers ────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _fmt(secs: int) -> str:
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ── main class ─────────────────────────────────────────────────────────────────

class PersistenceManager:

    def __init__(self):
        from qgis.core import QgsApplication
        data_dir = os.path.join(
            QgsApplication.qgisSettingsDirPath(), "time_tracker"
        )
        os.makedirs(data_dir, exist_ok=True)
        self._db_path = os.path.join(data_dir, "time_tracker.db")
        self._conn: sqlite3.Connection = None
        self._open()
        self._init_schema()
        self._recover_crashed_session()

    # ── connection ─────────────────────────────────────────────────────────────

    def _open(self):
        self._conn = sqlite3.connect(self._db_path, check_same_thread=True)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=NORMAL")

    # ── schema ─────────────────────────────────────────────────────────────────

    def _init_schema(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                project_path  TEXT    UNIQUE NOT NULL,
                project_name  TEXT    NOT NULL DEFAULT '',
                total_seconds INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT    NOT NULL,
                last_accessed TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id       INTEGER NOT NULL,
                start_time       TEXT    NOT NULL,
                end_time         TEXT,
                duration_seconds INTEGER NOT NULL DEFAULT 0,
                recovered        INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS active_session (
                id             INTEGER PRIMARY KEY CHECK (id = 1),
                project_path   TEXT    NOT NULL,
                start_time     TEXT    NOT NULL,
                last_heartbeat TEXT    NOT NULL,
                base_seconds   INTEGER NOT NULL DEFAULT 0
            );

            -- Indexes for query performance
            CREATE INDEX IF NOT EXISTS idx_projects_path
                ON projects(project_path);

            CREATE INDEX IF NOT EXISTS idx_sessions_project
                ON sessions(project_id);

            CREATE INDEX IF NOT EXISTS idx_sessions_start
                ON sessions(start_time);
        """)
        self._conn.commit()

    # ── crash recovery ─────────────────────────────────────────────────────────

    def _recover_crashed_session(self):
        """
        Check if an active session exists (leftover from a crash); if so,
        compute recovered time and update the database accordingly.
        """
        row = self._conn.execute(
            "SELECT * FROM active_session WHERE id=1"
        ).fetchone()
        if row is None:
            return

        try:
            hb = datetime.fromisoformat(row["last_heartbeat"])
            st = datetime.fromisoformat(row["start_time"])
            elapsed = max(0, int((hb - st).total_seconds()))
            recovered_total = row["base_seconds"] + elapsed

            self._ensure_project(row["project_path"])
            self._conn.execute(
                "UPDATE projects SET total_seconds=MAX(total_seconds, ?), "
                "last_accessed=? WHERE project_path=?",
                (recovered_total, _now(), row["project_path"]),
            )
            pid = self._project_id(row["project_path"])
            if pid and elapsed > 0:
                self._conn.execute(
                    "INSERT INTO sessions "
                    "(project_id, start_time, end_time, duration_seconds, recovered) "
                    "VALUES (?,?,?,?,1)",
                    (pid, row["start_time"], row["last_heartbeat"], elapsed),
                )
        except Exception:
            pass
        finally:
            self._conn.execute("DELETE FROM active_session")
            self._conn.commit()

    # ── internal helpers ───────────────────────────────────────────────────────

    def _ensure_project(self, project_path: str, project_name: str = None):
        """Ensure a project row exists; update name on every call."""
        if not project_name:
            if project_path == "__unsaved__":
                project_name = "Unsaved Project"
            else:
                project_name = os.path.splitext(
                    os.path.basename(project_path)
                )[0] or project_path

        self._conn.execute(
            "INSERT OR IGNORE INTO projects "
            "(project_path, project_name, created_at, last_accessed) "
            "VALUES (?,?,?,?)",
            (project_path, project_name, _now(), _now()),
        )
        self._conn.execute(
            "UPDATE projects SET project_name=?, last_accessed=? "
            "WHERE project_path=?",
            (project_name, _now(), project_path),
        )
        self._conn.commit()

    def _project_id(self, project_path: str):
        """Return the integer PK for a project path, or None."""
        row = self._conn.execute(
            "SELECT id FROM projects WHERE project_path=?", (project_path,)
        ).fetchone()
        return row["id"] if row else None

    # ── public API – reads ─────────────────────────────────────────────────────

    def get_project_seconds(self, project_path: str) -> int:
        row = self._conn.execute(
            "SELECT total_seconds FROM projects WHERE project_path=?",
            (project_path,),
        ).fetchone()
        return int(row["total_seconds"]) if row else 0

    def get_all_projects(self):
        """
        Returns all projects ordered by last_accessed DESC.
        Each row includes a computed 'session_count' column.
        """
        return self._conn.execute(
            "SELECT p.project_path, p.project_name, p.total_seconds, "
            "p.last_accessed, COUNT(s.id) AS session_count "
            "FROM projects p "
            "LEFT JOIN sessions s ON s.project_id = p.id "
            "GROUP BY p.id "
            "ORDER BY p.last_accessed DESC"
        ).fetchall()

    def get_sessions(self, project_path: str = None):
        """
        Returns sessions joined with project info.
        's.id' is included so callers can reference specific rows for deletion.
        """
        if project_path:
            return self._conn.execute(
                "SELECT s.id, s.start_time, s.end_time, s.duration_seconds, "
                "s.recovered, p.project_path, p.project_name "
                "FROM sessions s JOIN projects p ON s.project_id=p.id "
                "WHERE p.project_path=? ORDER BY s.start_time DESC",
                (project_path,),
            ).fetchall()
        return self._conn.execute(
            "SELECT s.id, s.start_time, s.end_time, s.duration_seconds, "
            "s.recovered, p.project_path, p.project_name "
            "FROM sessions s JOIN projects p ON s.project_id=p.id "
            "ORDER BY s.start_time DESC"
        ).fetchall()

    # ── public API – writes ────────────────────────────────────────────────────

    def update_project_seconds(
        self, project_path: str, total_seconds: int, project_name: str = None
    ):
        self._ensure_project(project_path, project_name)
        self._conn.execute(
            "UPDATE projects SET total_seconds=?, last_accessed=? "
            "WHERE project_path=?",
            (total_seconds, _now(), project_path),
        )
        self._conn.commit()

    def reset_project_seconds(self, project_path: str):
        """Zero the accumulated time for a project (keeps the project row and all sessions)."""
        self._conn.execute(
            "UPDATE projects SET total_seconds=0 WHERE project_path=?",
            (project_path,),
        )
        self._conn.commit()

    def delete_project(self, project_path: str):
        """
        Permanently remove a project row and ALL its sessions.
        The ON DELETE CASCADE constraint handles the sessions cleanup.
        """
        self._conn.execute(
            "DELETE FROM projects WHERE project_path=?", (project_path,)
        )
        self._conn.commit()

    def delete_session(self, session_id: int):
        """
        Remove a single session row and recalculate the owning project's
        total_seconds as the SUM of all remaining sessions for that project.
        """
        row = self._conn.execute(
            "SELECT project_id FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
        if not row:
            return

        project_id = row["project_id"]
        self._conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))

        result = self._conn.execute(
            "SELECT COALESCE(SUM(duration_seconds), 0) AS total "
            "FROM sessions WHERE project_id=?",
            (project_id,),
        ).fetchone()
        self._conn.execute(
            "UPDATE projects SET total_seconds=? WHERE id=?",
            (int(result["total"]), project_id),
        )
        self._conn.commit()

    def migrate_project_path(self, old_path: str, new_path: str, new_name: str = None):
        """
        Transfer accumulated time when an unsaved project is saved to disk.
        Merges old_path seconds into new_path and re-parents all sessions.
        No-op if old_path == new_path.
        """
        if old_path == new_path:
            return

        old_secs     = self.get_project_seconds(old_path)
        existing_secs = self.get_project_seconds(new_path)
        merged = old_secs + existing_secs

        self._ensure_project(new_path, new_name)
        self._conn.execute(
            "UPDATE projects SET total_seconds=? WHERE project_path=?",
            (merged, new_path),
        )
        old_id = self._project_id(old_path)
        new_id = self._project_id(new_path)
        if old_id and new_id:
            self._conn.execute(
                "UPDATE sessions SET project_id=? WHERE project_id=?",
                (new_id, old_id),
            )
        # Zero out the old entry (keep the row for auditability)
        self._conn.execute(
            "UPDATE projects SET total_seconds=0 WHERE project_path=?",
            (old_path,),
        )
        self._conn.commit()

    # ── active session (crash guard) ───────────────────────────────────────────

    def begin_active_session(self, project_path: str, base_seconds: int) -> str:
        now = _now()
        self._conn.execute(
            "INSERT OR REPLACE INTO active_session "
            "(id, project_path, start_time, last_heartbeat, base_seconds) "
            "VALUES (1,?,?,?,?)",
            (project_path, now, now, base_seconds),
        )
        self._conn.commit()
        return now

    def update_active_session_path(self, new_path: str):
        """
        Re-point the crash-guard sentinel at a new project path.
        Called by tracker.on_project_saved() when an unsaved project is first saved.
        """
        self._conn.execute(
            "UPDATE active_session SET project_path=? WHERE id=1",
            (new_path,),
        )
        self._conn.commit()

    def update_heartbeat(self):
        self._conn.execute(
            "UPDATE active_session SET last_heartbeat=? WHERE id=1",
            (_now(),),
        )
        self._conn.commit()

    def end_active_session(
        self, project_path: str, start_time_iso: str, duration_seconds: int
    ):
        self._ensure_project(project_path)
        pid = self._project_id(project_path)
        if pid and duration_seconds > 0:
            self._conn.execute(
                "INSERT INTO sessions "
                "(project_id, start_time, end_time, duration_seconds) "
                "VALUES (?,?,?,?)",
                (pid, start_time_iso, _now(), duration_seconds),
            )
        self._conn.execute("DELETE FROM active_session")
        self._conn.commit()

    def clear_active_session(self):
        self._conn.execute("DELETE FROM active_session")
        self._conn.commit()

    # ── export ─────────────────────────────────────────────────────────────────

    def export_csv(self, path: str):
        projects = self.get_all_projects()
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow([
                "project_name", "project_path", "total_seconds",
                "total_time_hms", "session_count", "last_accessed",
            ])
            for p in projects:
                w.writerow([
                    p["project_name"],
                    p["project_path"],
                    p["total_seconds"],
                    _fmt(p["total_seconds"]),
                    p["session_count"],
                    p["last_accessed"],
                ])

    def export_json(self, path: str):
        projects = self.get_all_projects()
        out = []
        for p in projects:
            sessions = self.get_sessions(p["project_path"])
            out.append({
                "project_name":  p["project_name"],
                "project_path":  p["project_path"],
                "total_seconds": p["total_seconds"],
                "total_time_hms": _fmt(p["total_seconds"]),
                "session_count": p["session_count"],
                "last_accessed": p["last_accessed"],
                "sessions": [
                    {
                        "start_time":       s["start_time"],
                        "end_time":         s["end_time"],
                        "duration_seconds": s["duration_seconds"],
                        "recovered":        bool(s["recovered"]),
                    }
                    for s in sessions
                ],
            })
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, ensure_ascii=False)

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None