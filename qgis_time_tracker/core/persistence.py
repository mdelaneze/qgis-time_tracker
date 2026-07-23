"""
SQLite-backed persistence layer — QGIS 4 / Qt 6 compatible.

Schema (5 tables):
  projects      – one row per .qgs/.qgz file; stores cumulative total_seconds.
  sessions      – one row per tracked work session; used for history & export.
  active_session– at most ONE row (id=1); written every heartbeat so that
                  QGIS crashes lose at most 5 s of tracking data.
  daily_totals  – materialised daily aggregates for the heatmap/chart view.
  recovery_errors – sessões inválidas preservadas para diagnóstico.

Schema migration
----------------
  Um backup versionado é criado antes de _init_schema()/_migrate(). As etapas
  seguintes tratam upgrades de versões antigas em transações independentes.

Crash-recovery logic runs in __init__ before any other operation:
  if active_session exists → compute recovered seconds from last_heartbeat,
  update projects.total_seconds, write a completed session row and delete the
  sentinel. Registros inválidos são movidos para recovery_errors.

WAL journal mode is set so SQLite never writes partial pages to the main db
file; a hard kill cannot corrupt the database.
"""

import csv
import json
import logging
import ntpath
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone

_LOG = logging.getLogger(__name__)

# ── helpers ────────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today() -> str:
    return date.today().isoformat()


def _fmt(secs: int) -> str:
    h, rem = divmod(int(secs), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def normalize_project_path(project_path: str) -> str:
    """Produz uma chave estável para o mesmo arquivo em cada sistema operacional."""
    if not project_path or project_path.startswith("__unsaved__"):
        return project_path
    drive, _ = ntpath.splitdrive(project_path)
    if os.name == "nt" or drive or project_path.startswith("\\\\"):
        return ntpath.normcase(ntpath.normpath(project_path))
    normalized = os.path.abspath(os.path.normpath(project_path))
    return os.path.realpath(normalized)


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _split_daily_seconds(start_time_iso: str, duration_seconds: int):
    """Divide uma duração entre os dias civis do fuso horário local."""
    remaining = max(0, int(duration_seconds))
    if remaining == 0:
        return []

    local_tz = datetime.now().astimezone().tzinfo
    cursor = _parse_timestamp(start_time_iso).astimezone(local_tz)
    buckets = []
    while remaining > 0:
        next_day = cursor.date() + timedelta(days=1)
        midnight = datetime.combine(next_day, datetime.min.time(), tzinfo=local_tz)
        until_midnight = max(1, int(midnight.timestamp() - cursor.timestamp()))
        allocated = min(remaining, until_midnight)
        buckets.append((cursor.date().isoformat(), allocated))
        cursor = datetime.fromtimestamp(cursor.timestamp() + allocated, tz=local_tz)
        remaining -= allocated
    return buckets


# ── main class ─────────────────────────────────────────────────────────────────


class PersistenceManager:

    # Current schema version — bump when adding new migrations.
    _SCHEMA_VERSION = 8

    def __init__(self, data_dir=None):
        if data_dir is None:
            from qgis.core import QgsApplication

            data_dir = os.path.join(
                QgsApplication.qgisSettingsDirPath(), "time_tracker"
            )
        os.makedirs(data_dir, exist_ok=True)
        self._db_path = os.path.join(data_dir, "time_tracker.db")
        self._database_existed = os.path.isfile(self._db_path)
        self._conn: sqlite3.Connection = None
        self._open()
        self._backup_before_migration()
        self._init_schema()
        self._migrate()
        self._validate_integrity()
        self._recover_crashed_session()

    # ── connection ─────────────────────────────────────────────────────────────

    def _open(self):
        self._conn = sqlite3.connect(self._db_path, check_same_thread=True)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=5000")

    # ── schema ─────────────────────────────────────────────────────────────────

    def _init_schema(self):
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS projects (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                project_path  TEXT    UNIQUE NOT NULL,
                project_name  TEXT    NOT NULL DEFAULT '',
                total_seconds INTEGER NOT NULL DEFAULT 0,
                counter_baseline INTEGER NOT NULL DEFAULT 0,
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
                counts_toward_total INTEGER NOT NULL DEFAULT 1,
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS active_session (
                id             INTEGER PRIMARY KEY CHECK (id = 1),
                project_path   TEXT    NOT NULL,
                start_time     TEXT    NOT NULL,
                last_heartbeat TEXT    NOT NULL,
                base_seconds   INTEGER NOT NULL DEFAULT 0,
                min_session_seconds INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS daily_totals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                work_date   TEXT    NOT NULL,
                project_id  INTEGER NOT NULL,
                day_seconds INTEGER NOT NULL DEFAULT 0,
                UNIQUE (work_date, project_id),
                FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS recovery_errors (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at    TEXT NOT NULL,
                project_path   TEXT NOT NULL,
                start_time     TEXT,
                last_heartbeat TEXT,
                error_message  TEXT NOT NULL,
                notified       INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_projects_path
                ON projects(project_path);
            CREATE INDEX IF NOT EXISTS idx_sessions_project
                ON sessions(project_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_start
                ON sessions(start_time);
            CREATE INDEX IF NOT EXISTS idx_daily_date
                ON daily_totals(work_date);
        """
        )
        self._conn.commit()

        # Seed schema_version if table is empty
        count = self._conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
        if count == 0:
            self._conn.execute("INSERT INTO schema_version (version) VALUES (0)")
            self._conn.commit()

    def _backup_before_migration(self):
        if not self._database_existed:
            return
        try:
            row = self._conn.execute("SELECT version FROM schema_version").fetchone()
            current = int(row["version"]) if row else 0
        except sqlite3.Error:
            current = 0
        if current >= self._SCHEMA_VERSION:
            return
        backup_path = f"{self._db_path}.bak-v{current}"
        if os.path.exists(backup_path):
            return
        backup = sqlite3.connect(backup_path)
        try:
            self._conn.backup(backup)
        finally:
            backup.close()

    def _validate_integrity(self):
        result = self._conn.execute("PRAGMA quick_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(
                "O banco do Controle de Tempo falhou na verificação de integridade: "
                f"{result}. Restaure o backup versionado antes de continuar."
            )

    # ── migrations ─────────────────────────────────────────────────────────────

    def _migrate(self):
        """
        Run all pending schema migrations in order.
        Safe to call repeatedly; each step checks the current version first.
        Preserves all existing data from Qt5/QGIS 3 installs.
        """
        current = self._conn.execute("SELECT version FROM schema_version").fetchone()[
            "version"
        ]
        if current > self._SCHEMA_VERSION:
            raise RuntimeError(
                "O banco do Controle de Tempo foi criado por uma versão mais nova "
                f"(schema {current}; suportado: {self._SCHEMA_VERSION})."
            )

        if current < 1:
            # v1 – back-fill daily_totals from existing sessions table
            try:
                rows = self._conn.execute(
                    "SELECT s.project_id, s.start_time, s.duration_seconds "
                    "FROM sessions s WHERE s.duration_seconds > 0"
                ).fetchall()
                for row in rows:
                    work_date = str(row["start_time"])[:10]
                    self._conn.execute(
                        "INSERT INTO daily_totals (work_date, project_id, day_seconds) "
                        "VALUES (?,?,?) "
                        "ON CONFLICT(work_date, project_id) DO UPDATE "
                        "SET day_seconds = day_seconds + excluded.day_seconds",
                        (work_date, row["project_id"], row["duration_seconds"]),
                    )
                self._conn.execute("UPDATE schema_version SET version=1")
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            current = 1

        if current < 2:
            # v2 – ensure projects.created_at is never NULL (guard for old rows)
            try:
                self._conn.execute(
                    "UPDATE projects SET created_at=last_accessed "
                    "WHERE created_at IS NULL OR created_at=''"
                )
                self._conn.execute("UPDATE schema_version SET version=2")
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            current = 2

        if current < 3:
            # v3 – permite zerar o contador sem apagar o histórico de sessões.
            try:
                columns = {
                    row["name"]
                    for row in self._conn.execute("PRAGMA table_info(sessions)")
                }
                if "counts_toward_total" not in columns:
                    self._conn.execute(
                        "ALTER TABLE sessions ADD COLUMN "
                        "counts_toward_total INTEGER NOT NULL DEFAULT 1"
                    )
                self._conn.execute("UPDATE schema_version SET version=3")
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            current = 3

        if current < 4:
            # v4 – recuperações após falha também respeitam a duração mínima.
            try:
                columns = {
                    row["name"]
                    for row in self._conn.execute("PRAGMA table_info(active_session)")
                }
                if "min_session_seconds" not in columns:
                    self._conn.execute(
                        "ALTER TABLE active_session ADD COLUMN "
                        "min_session_seconds INTEGER NOT NULL DEFAULT 0"
                    )
                self._conn.execute("UPDATE schema_version SET version=4")
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            current = 4

        if current < 5:
            # v5 – reconcilia resets feitos por versões que mantinham sessões.
            try:
                columns = {
                    row["name"]
                    for row in self._conn.execute("PRAGMA table_info(projects)")
                }
                added_baseline = "counter_baseline" not in columns
                if added_baseline:
                    self._conn.execute(
                        "ALTER TABLE projects ADD COLUMN "
                        "counter_baseline INTEGER NOT NULL DEFAULT 0"
                    )
                    self._reconcile_legacy_project_totals()
                self._conn.execute("UPDATE schema_version SET version=5")
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            current = 5

        if current < 6:
            # v6 – consolida caminhos equivalentes, especialmente no Windows.
            self._commit_migration(6, self._normalize_all_project_paths)
            current = 6

        if current < 7:
            # recovery_errors é criado por _init_schema para bancos antigos.
            self._commit_migration(7)
            current = 7

        if current < 8:
            self._commit_migration(8, self._ensure_recovery_notified_column)

    def _commit_migration(self, version: int, operation=None):
        try:
            if operation is not None:
                operation()
            self._conn.execute("UPDATE schema_version SET version=?", (version,))
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def _normalize_all_project_paths(self):
        self._normalize_existing_project_paths()
        active = self._conn.execute(
            "SELECT project_path FROM active_session WHERE id=1"
        ).fetchone()
        if active:
            self._conn.execute(
                "UPDATE active_session SET project_path=? WHERE id=1",
                (normalize_project_path(active["project_path"]),),
            )

    def _ensure_recovery_notified_column(self):
        columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(recovery_errors)")
        }
        if "notified" not in columns:
            self._conn.execute(
                "ALTER TABLE recovery_errors ADD COLUMN "
                "notified INTEGER NOT NULL DEFAULT 0"
            )

    def _normalize_existing_project_paths(self):
        projects = self._conn.execute(
            "SELECT id, project_path FROM projects ORDER BY id"
        ).fetchall()
        groups = {}
        for project in projects:
            normalized = normalize_project_path(project["project_path"])
            groups.setdefault(normalized, []).append(project)

        for normalized, rows in groups.items():
            keeper = next(
                (row for row in rows if row["project_path"] == normalized), rows[0]
            )
            for row in rows:
                if row["id"] != keeper["id"]:
                    self._merge_project_rows(row["id"], keeper["id"])
            self._conn.execute(
                "UPDATE projects SET project_path=? WHERE id=?",
                (normalized, keeper["id"]),
            )

    def _merge_project_rows(self, source_id: int, target_id: int):
        source = self._conn.execute(
            "SELECT total_seconds, counter_baseline FROM projects WHERE id=?",
            (source_id,),
        ).fetchone()
        target = self._conn.execute(
            "SELECT total_seconds, counter_baseline FROM projects WHERE id=?",
            (target_id,),
        ).fetchone()
        self._conn.execute(
            "UPDATE projects SET total_seconds=?, counter_baseline=? WHERE id=?",
            (
                int(source["total_seconds"]) + int(target["total_seconds"]),
                int(source["counter_baseline"]) + int(target["counter_baseline"]),
                target_id,
            ),
        )
        self._conn.execute(
            "UPDATE sessions SET project_id=? WHERE project_id=?",
            (target_id, source_id),
        )
        source_daily = self._conn.execute(
            "SELECT work_date, day_seconds FROM daily_totals WHERE project_id=?",
            (source_id,),
        ).fetchall()
        for row in source_daily:
            self._conn.execute(
                "INSERT INTO daily_totals "
                "(work_date, project_id, day_seconds) VALUES (?,?,?) "
                "ON CONFLICT(work_date, project_id) DO UPDATE "
                "SET day_seconds=day_seconds + excluded.day_seconds",
                (row["work_date"], target_id, row["day_seconds"]),
            )
        self._conn.execute(
            "DELETE FROM daily_totals WHERE project_id=?", (source_id,)
        )
        self._conn.execute("DELETE FROM projects WHERE id=?", (source_id,))

    def _reconcile_legacy_project_totals(self):
        """Preserva contadores antigos sem voltar a contabilizar sessões resetadas."""
        projects = self._conn.execute(
            "SELECT id, total_seconds FROM projects"
        ).fetchall()
        for project in projects:
            sessions = self._conn.execute(
                "SELECT id, duration_seconds FROM sessions "
                "WHERE project_id=? ORDER BY id DESC",
                (project["id"],),
            ).fetchall()
            target = int(project["total_seconds"])
            selected = []
            running = 0
            for session in sessions:
                candidate = running + int(session["duration_seconds"])
                if candidate > target:
                    break
                selected.append(session["id"])
                running = candidate
                if running == target:
                    break

            self._conn.execute(
                "UPDATE sessions SET counts_toward_total=0 WHERE project_id=?",
                (project["id"],),
            )
            if running == target and selected:
                placeholders = ",".join("?" for _ in selected)
                self._conn.execute(
                    f"UPDATE sessions SET counts_toward_total=1 "
                    f"WHERE id IN ({placeholders})",
                    selected,
                )
                baseline = 0
            else:
                baseline = target
            self._conn.execute(
                "UPDATE projects SET counter_baseline=? WHERE id=?",
                (baseline, project["id"]),
            )

    # ── crash recovery ─────────────────────────────────────────────────────────

    def _recover_crashed_session(self):
        row = self._conn.execute("SELECT * FROM active_session WHERE id=1").fetchone()
        if row is None:
            return

        try:
            hb = _parse_timestamp(row["last_heartbeat"])
            st = _parse_timestamp(row["start_time"])
            elapsed = max(0, int((hb - st).total_seconds()))
            if elapsed < int(row["min_session_seconds"]):
                with self._conn:
                    self._conn.execute("DELETE FROM active_session WHERE id=1")
                return
            recovered_total = row["base_seconds"] + elapsed

            with self._conn:
                self._ensure_project(row["project_path"], commit=False)
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
                    self._add_daily_buckets(pid, row["start_time"], elapsed)
                self._conn.execute("DELETE FROM active_session WHERE id=1")
        except Exception as exc:
            error_message = f"{type(exc).__name__}: {exc}"
            _LOG.exception(
                "Não foi possível recuperar a sessão ativa de %s.",
                row["project_path"],
            )
            try:
                with self._conn:
                    self._conn.execute(
                        "INSERT INTO recovery_errors "
                        "(recorded_at, project_path, start_time, last_heartbeat, "
                        "error_message) VALUES (?,?,?,?,?)",
                        (
                            _now(),
                            row["project_path"],
                            row["start_time"],
                            row["last_heartbeat"],
                            error_message,
                        ),
                    )
                    self._conn.execute("DELETE FROM active_session WHERE id=1")
            except sqlite3.Error:
                _LOG.exception(
                    "Também não foi possível preservar a falha em recovery_errors; "
                    "a sessão ativa foi mantida."
                )

    # ── internal helpers ───────────────────────────────────────────────────────

    def _ensure_project(
        self, project_path: str, project_name: str = None, commit: bool = True
    ):
        project_path = normalize_project_path(project_path)
        if not project_name:
            if project_path.startswith("__unsaved__"):
                project_name = "Projeto não salvo"
            else:
                project_name = (
                    os.path.splitext(os.path.basename(project_path))[0] or project_path
                )

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
        if commit:
            self._conn.commit()

    def _add_daily_buckets(
        self, project_id: int, start_time_iso: str, duration_seconds: int
    ):
        for work_date, day_seconds in _split_daily_seconds(
            start_time_iso, duration_seconds
        ):
            self._conn.execute(
                "INSERT INTO daily_totals (work_date, project_id, day_seconds) "
                "VALUES (?,?,?) "
                "ON CONFLICT(work_date, project_id) DO UPDATE "
                "SET day_seconds = day_seconds + excluded.day_seconds",
                (work_date, project_id, day_seconds),
            )

    def _project_id(self, project_path: str):
        project_path = normalize_project_path(project_path)
        row = self._conn.execute(
            "SELECT id FROM projects WHERE project_path=?", (project_path,)
        ).fetchone()
        return row["id"] if row else None

    # ── public API – reads ─────────────────────────────────────────────────────

    def get_project_seconds(self, project_path: str) -> int:
        project_path = normalize_project_path(project_path)
        row = self._conn.execute(
            "SELECT total_seconds FROM projects WHERE project_path=?",
            (project_path,),
        ).fetchone()
        return int(row["total_seconds"]) if row else 0

    def get_all_projects(self):
        return self._conn.execute(
            "SELECT p.project_path, p.project_name, p.total_seconds, "
            "p.last_accessed, p.created_at, COUNT(s.id) AS session_count "
            "FROM projects p "
            "LEFT JOIN sessions s ON s.project_id = p.id "
            "GROUP BY p.id "
            "ORDER BY p.last_accessed DESC"
        ).fetchall()

    def get_sessions(self, project_path: str = None):
        if project_path:
            project_path = normalize_project_path(project_path)
            return self._conn.execute(
                "SELECT s.id, s.start_time, s.end_time, s.duration_seconds, "
                "s.recovered, s.counts_toward_total, "
                "p.project_path, p.project_name "
                "FROM sessions s JOIN projects p ON s.project_id=p.id "
                "WHERE p.project_path=? ORDER BY s.start_time DESC",
                (project_path,),
            ).fetchall()
        return self._conn.execute(
            "SELECT s.id, s.start_time, s.end_time, s.duration_seconds, "
            "s.recovered, s.counts_toward_total, p.project_path, p.project_name "
            "FROM sessions s JOIN projects p ON s.project_id=p.id "
            "ORDER BY s.start_time DESC"
        ).fetchall()

    def get_daily_totals(self, days: int = 365):
        """
        Returns daily aggregate seconds for the last `days` calendar days
        across ALL projects.  Used by the heatmap / bar chart.
        """
        since = (date.today() - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            "SELECT work_date, SUM(day_seconds) AS total_seconds "
            "FROM daily_totals "
            "WHERE work_date >= ? "
            "GROUP BY work_date "
            "ORDER BY work_date ASC",
            (since,),
        ).fetchall()
        return rows

    def get_weekly_totals(self, weeks: int = 12):
        """
        Returns weekly totals (Mon–Sun) for the last `weeks` weeks.
        Returns list of dicts: {week_start: str, total_seconds: int}.
        """
        weeks = max(1, int(weeks))
        today = date.today()
        current_week = today - timedelta(days=today.weekday())
        since = current_week - timedelta(weeks=weeks - 1)
        rows = self._conn.execute(
            "SELECT work_date, SUM(day_seconds) AS total_seconds "
            "FROM daily_totals WHERE work_date BETWEEN ? AND ? "
            "GROUP BY work_date ORDER BY work_date",
            (since.isoformat(), today.isoformat()),
        ).fetchall()
        buckets: dict = {}
        for row in rows:
            d = date.fromisoformat(row["work_date"])
            week_start = (d - timedelta(days=d.weekday())).isoformat()
            buckets[week_start] = buckets.get(week_start, 0) + row["total_seconds"]
        return [
            {"week_start": k, "total_seconds": v} for k, v in sorted(buckets.items())
        ]

    def get_current_week_seconds(self) -> int:
        """Total registrado desde a segunda-feira da semana local atual."""
        today = date.today()
        week_start = (today - timedelta(days=today.weekday())).isoformat()
        row = self._conn.execute(
            "SELECT COALESCE(SUM(day_seconds),0) AS total "
            "FROM daily_totals WHERE work_date BETWEEN ? AND ?",
            (week_start, today.isoformat()),
        ).fetchone()
        return int(row["total"]) if row else 0

    def get_today_seconds(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(day_seconds),0) AS total "
            "FROM daily_totals WHERE work_date=?",
            (_today(),),
        ).fetchone()
        return int(row["total"]) if row else 0

    def get_streak_days(self) -> int:
        """Number of consecutive days with recorded work ending today or yesterday."""
        rows = self._conn.execute(
            "SELECT DISTINCT work_date FROM daily_totals "
            "WHERE day_seconds > 0 ORDER BY work_date DESC"
        ).fetchall()
        if not rows:
            return 0
        streak = 0
        expected = date.today()
        for row in rows:
            d = date.fromisoformat(row["work_date"])
            if d == expected or (streak == 0 and d == expected - timedelta(days=1)):
                streak += 1
                expected = d - timedelta(days=1)
            else:
                break
        return streak

    def get_recovery_errors(self):
        """Falhas de recuperação preservadas para diagnóstico e aviso ao usuário."""
        return self._conn.execute(
            "SELECT id, recorded_at, project_path, start_time, last_heartbeat, "
            "error_message FROM recovery_errors ORDER BY id DESC"
        ).fetchall()

    def consume_recovery_errors(self):
        """Retorna avisos ainda não exibidos e os marca como notificados."""
        with self._conn:
            rows = self._conn.execute(
                "SELECT id, recorded_at, project_path, start_time, last_heartbeat, "
                "error_message FROM recovery_errors WHERE notified=0 ORDER BY id"
            ).fetchall()
            if rows:
                self._conn.execute(
                    "UPDATE recovery_errors SET notified=1 WHERE notified=0"
                )
        return rows

    # ── public API – writes ────────────────────────────────────────────────────

    def update_project_seconds(
        self, project_path: str, total_seconds: int, project_name: str = None
    ):
        project_path = normalize_project_path(project_path)
        self._ensure_project(project_path, project_name)
        self._conn.execute(
            "UPDATE projects SET total_seconds=?, last_accessed=? "
            "WHERE project_path=?",
            (total_seconds, _now(), project_path),
        )
        self._conn.commit()

    def reset_project_seconds(self, project_path: str):
        """Zera o contador e mantém as sessões como histórico não contabilizado."""
        project_path = normalize_project_path(project_path)
        with self._conn:
            project_id = self._project_id(project_path)
            self._conn.execute(
                "UPDATE projects SET total_seconds=0, counter_baseline=0 "
                "WHERE project_path=?",
                (project_path,),
            )
            if project_id is not None:
                self._conn.execute(
                    "UPDATE sessions SET counts_toward_total=0 WHERE project_id=?",
                    (project_id,),
                )

    def delete_project(self, project_path: str):
        project_path = normalize_project_path(project_path)
        self._conn.execute("DELETE FROM projects WHERE project_path=?", (project_path,))
        self._conn.commit()

    def delete_session(self, session_id: int):
        row = self._conn.execute(
            "SELECT project_id, duration_seconds, start_time "
            "FROM sessions WHERE id=?",
            (session_id,),
        ).fetchone()
        if not row:
            return

        project_id = row["project_id"]
        dur = row["duration_seconds"]
        work_date = str(row["start_time"])[:10]

        self._conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))

        result = self._conn.execute(
            "SELECT p.counter_baseline + COALESCE(SUM(s.duration_seconds), 0) AS total "
            "FROM projects p LEFT JOIN sessions s "
            "ON s.project_id=p.id AND s.counts_toward_total=1 WHERE p.id=?",
            (project_id,),
        ).fetchone()
        self._conn.execute(
            "UPDATE projects SET total_seconds=? WHERE id=?",
            (int(result["total"]), project_id),
        )

        # Subtract from daily_totals (floor at 0)
        self._conn.execute(
            "UPDATE daily_totals SET day_seconds=MAX(0, day_seconds - ?) "
            "WHERE work_date=? AND project_id=?",
            (dur, work_date, project_id),
        )
        self._conn.commit()

    def migrate_project_path(self, old_path: str, new_path: str, new_name: str = None):
        old_path = normalize_project_path(old_path)
        new_path = normalize_project_path(new_path)
        if old_path == new_path:
            return

        old_secs = self.get_project_seconds(old_path)
        existing_secs = self.get_project_seconds(new_path)
        merged = old_secs + existing_secs

        with self._conn:
            self._ensure_project(new_path, new_name, commit=False)
            old_id = self._project_id(old_path)
            new_id = self._project_id(new_path)
            old_baseline = 0
            new_baseline = 0
            if old_id:
                old_baseline = self._conn.execute(
                    "SELECT counter_baseline FROM projects WHERE id=?", (old_id,)
                ).fetchone()["counter_baseline"]
            if new_id:
                new_baseline = self._conn.execute(
                    "SELECT counter_baseline FROM projects WHERE id=?", (new_id,)
                ).fetchone()["counter_baseline"]
            self._conn.execute(
                "UPDATE projects SET total_seconds=?, counter_baseline=? "
                "WHERE project_path=?",
                (merged, old_baseline + new_baseline, new_path),
            )
            if old_id and new_id:
                self._conn.execute(
                    "UPDATE sessions SET project_id=? WHERE project_id=?",
                    (new_id, old_id),
                )
                old_daily = self._conn.execute(
                    "SELECT work_date, day_seconds FROM daily_totals WHERE project_id=?",
                    (old_id,),
                ).fetchall()
                for row in old_daily:
                    self._conn.execute(
                        "INSERT INTO daily_totals "
                        "(work_date, project_id, day_seconds) VALUES (?,?,?) "
                        "ON CONFLICT(work_date, project_id) DO UPDATE "
                        "SET day_seconds = day_seconds + excluded.day_seconds",
                        (row["work_date"], new_id, row["day_seconds"]),
                    )
                self._conn.execute(
                    "DELETE FROM daily_totals WHERE project_id=?", (old_id,)
                )
                self._conn.execute("DELETE FROM projects WHERE id=?", (old_id,))

    # ── active session (crash guard) ───────────────────────────────────────────

    def begin_active_session(
        self,
        project_path: str,
        base_seconds: int,
        min_session_seconds: int = 0,
    ) -> str:
        project_path = normalize_project_path(project_path)
        now = _now()
        self._conn.execute(
            "INSERT OR REPLACE INTO active_session "
            "(id, project_path, start_time, last_heartbeat, base_seconds, "
            "min_session_seconds) VALUES (1,?,?,?,?,?)",
            (
                project_path,
                now,
                now,
                base_seconds,
                max(0, int(min_session_seconds)),
            ),
        )
        self._conn.commit()
        return now

    def update_heartbeat(self):
        self._conn.execute(
            "UPDATE active_session SET last_heartbeat=? WHERE id=1",
            (_now(),),
        )
        self._conn.commit()

    def end_active_session(
        self, project_path: str, start_time_iso: str, duration_seconds: int
    ):
        project_path = normalize_project_path(project_path)
        with self._conn:
            self._ensure_project(project_path, commit=False)
            pid = self._project_id(project_path)
            if pid and duration_seconds > 0:
                end_time = (
                    _parse_timestamp(start_time_iso)
                    + timedelta(seconds=int(duration_seconds))
                ).isoformat(timespec="seconds")
                self._conn.execute(
                    "INSERT INTO sessions "
                    "(project_id, start_time, end_time, duration_seconds) "
                    "VALUES (?,?,?,?)",
                    (pid, start_time_iso, end_time, duration_seconds),
                )
                self._add_daily_buckets(pid, start_time_iso, duration_seconds)
            self._conn.execute("DELETE FROM active_session")

    def live_today_seconds(self, start_time_iso: str, duration_seconds: int) -> int:
        """Parcela de uma sessão ainda ativa pertencente ao dia local atual."""
        return sum(
            seconds
            for work_date, seconds in _split_daily_seconds(
                start_time_iso, duration_seconds
            )
            if work_date == _today()
        )

    def live_current_week_seconds(
        self, start_time_iso: str, duration_seconds: int
    ) -> int:
        """Parcela de uma sessão ativa pertencente à semana local atual."""
        today = date.today()
        week_start = (today - timedelta(days=today.weekday())).isoformat()
        return sum(
            seconds
            for work_date, seconds in _split_daily_seconds(
                start_time_iso, duration_seconds
            )
            if week_start <= work_date <= today.isoformat()
        )

    def clear_active_session(self):
        self._conn.execute("DELETE FROM active_session")
        self._conn.commit()

    # ── export ─────────────────────────────────────────────────────────────────

    def export_csv(self, path: str):
        projects = self.get_all_projects()
        with open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(
                [
                    "project_name",
                    "project_path",
                    "total_seconds",
                    "total_time_hms",
                    "session_count",
                    "last_accessed",
                    "session_start",
                    "session_end",
                    "session_duration_seconds",
                    "session_recovered",
                    "session_counts_toward_total",
                ]
            )
            for p in projects:
                sessions = self.get_sessions(p["project_path"])
                rows = sessions or [None]
                for session in rows:
                    w.writerow(
                        [
                            p["project_name"],
                            p["project_path"],
                            p["total_seconds"],
                            _fmt(p["total_seconds"]),
                            p["session_count"],
                            p["last_accessed"],
                            session["start_time"] if session else "",
                            session["end_time"] if session else "",
                            session["duration_seconds"] if session else "",
                            bool(session["recovered"]) if session else "",
                            bool(session["counts_toward_total"]) if session else "",
                        ]
                    )

    def export_json(self, path: str):
        projects = self.get_all_projects()
        out = []
        for p in projects:
            sessions = self.get_sessions(p["project_path"])
            out.append(
                {
                    "project_name": p["project_name"],
                    "project_path": p["project_path"],
                    "total_seconds": p["total_seconds"],
                    "total_time_hms": _fmt(p["total_seconds"]),
                    "session_count": p["session_count"],
                    "last_accessed": p["last_accessed"],
                    "sessions": [
                        {
                            "start_time": s["start_time"],
                            "end_time": s["end_time"],
                            "duration_seconds": s["duration_seconds"],
                            "recovered": bool(s["recovered"]),
                            "counts_toward_total": bool(s["counts_toward_total"]),
                        }
                        for s in sessions
                    ],
                }
            )
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=2, ensure_ascii=False)

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
