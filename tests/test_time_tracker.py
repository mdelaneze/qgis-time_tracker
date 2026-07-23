import sqlite3
from datetime import date, datetime, time, timedelta, timezone

from qgis_time_tracker.core.persistence import PersistenceManager
from qgis_time_tracker.core.persistence import (
    _split_daily_seconds,
    normalize_project_path,
)
from qgis_time_tracker.core.tracker import TimeTracker, TrackerState


def _record_session(database, project_path, seconds):
    started_at = database.begin_active_session(project_path, 0)
    database.update_project_seconds(project_path, seconds)
    database.end_active_session(project_path, started_at, seconds)


def test_persistence_records_session_daily_total_and_exports(tmp_path):
    database = PersistenceManager(str(tmp_path / "profile"))
    _record_session(database, "/projetos/safra.qgz", 125)

    assert database.get_project_seconds("/projetos/safra.qgz") == 125
    assert database.get_today_seconds() == 125
    assert database.get_sessions("/projetos/safra.qgz")[0]["duration_seconds"] == 125

    csv_path = tmp_path / "tempo.csv"
    json_path = tmp_path / "tempo.json"
    database.export_csv(str(csv_path))
    database.export_json(str(json_path))

    assert "total_time_hms" in csv_path.read_text(encoding="utf-8")
    assert '"duration_seconds": 125' in json_path.read_text(encoding="utf-8")
    database.close()


def test_project_path_migration_merges_existing_daily_totals(tmp_path):
    database = PersistenceManager(str(tmp_path / "profile"))
    old_path = "__unsaved__"
    saved_path = "/projetos/safra.qgz"
    _record_session(database, old_path, 40)
    _record_session(database, saved_path, 20)

    database.migrate_project_path(old_path, saved_path, "Safra")

    assert database.get_project_seconds(saved_path) == 60
    assert len(database.get_sessions(saved_path)) == 2
    assert database.get_today_seconds() == 60
    assert database.get_project_seconds(old_path) == 0
    assert all(p["project_path"] != old_path for p in database.get_all_projects())
    database.close()


def test_daily_seconds_are_split_at_local_midnight():
    local_tz = datetime.now().astimezone().tzinfo
    start = datetime.combine(date.today(), time(23, 59, 30), tzinfo=local_tz)

    buckets = _split_daily_seconds(start.isoformat(), 90)

    assert buckets == [
        (date.today().isoformat(), 30),
        ((date.today() + timedelta(days=1)).isoformat(), 60),
    ]


def test_reset_preserves_history_without_recounting_old_sessions(tmp_path):
    database = PersistenceManager(str(tmp_path / "profile"))
    project = "/projetos/safra.qgz"
    _record_session(database, project, 120)
    database.reset_project_seconds(project)

    started_at = database.begin_active_session(project, 0)
    database.update_project_seconds(project, 30)
    database.end_active_session(project, started_at, 30)
    new_session = next(
        row for row in database.get_sessions(project) if row["duration_seconds"] == 30
    )
    database.delete_session(new_session["id"])

    assert database.get_project_seconds(project) == 0
    old_session = database.get_sessions(project)[0]
    assert old_session["duration_seconds"] == 120
    assert old_session["counts_toward_total"] == 0
    database.close()


def test_current_week_ignores_previous_week_bucket(tmp_path):
    database = PersistenceManager(str(tmp_path / "profile"))
    project = "/projetos/safra.qgz"
    database._ensure_project(project, "Safra")
    project_id = database._project_id(project)
    today = date.today()
    previous_sunday = today - timedelta(days=today.weekday() + 1)
    database._conn.executemany(
        "INSERT INTO daily_totals(work_date, project_id, day_seconds) VALUES (?,?,?)",
        [
            (previous_sunday.isoformat(), project_id, 3600),
            (today.isoformat(), project_id, 7200),
        ],
    )
    database._conn.commit()

    assert database.get_current_week_seconds() == 7200
    assert database.get_weekly_totals(weeks=1) == [
        {
            "week_start": (
                today - timedelta(days=today.weekday())
            ).isoformat(),
            "total_seconds": 7200,
        }
    ]
    database.close()


def test_invalid_crash_record_is_quarantined_for_diagnosis(tmp_path):
    profile = str(tmp_path / "profile")
    database = PersistenceManager(profile)
    database._conn.execute(
        "INSERT INTO active_session "
        "(id, project_path, start_time, last_heartbeat, base_seconds) "
        "VALUES (1, ?, ?, ?, 0)",
        ("/projetos/safra.qgz", "invalid", "invalid"),
    )
    database._conn.commit()
    database.close()

    recovered = PersistenceManager(profile)
    active = recovered._conn.execute("SELECT id FROM active_session").fetchone()
    errors = recovered.get_recovery_errors()

    assert active is None
    assert errors[0]["project_path"] == "/projetos/safra.qgz"
    assert "ValueError" in errors[0]["error_message"]
    assert len(recovered.consume_recovery_errors()) == 1
    assert recovered.consume_recovery_errors() == []
    recovered.close()


def test_crash_recovery_discards_session_below_minimum(tmp_path):
    profile = str(tmp_path / "profile")
    database = PersistenceManager(profile)
    started = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    heartbeat = started + timedelta(seconds=10)
    database._conn.execute(
        "INSERT INTO active_session "
        "(id, project_path, start_time, last_heartbeat, base_seconds, "
        "min_session_seconds) VALUES (1, ?, ?, ?, 0, 60)",
        (
            "/projetos/safra.qgz",
            started.isoformat(),
            heartbeat.isoformat(),
        ),
    )
    database._conn.commit()
    database.close()

    recovered = PersistenceManager(profile)

    assert recovered.get_sessions("/projetos/safra.qgz") == []
    assert (
        recovered._conn.execute("SELECT id FROM active_session").fetchone() is None
    )
    recovered.close()


def test_schema_migration_reconciles_legacy_reset_history(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    connection = sqlite3.connect(profile / "time_tracker.db")
    connection.executescript(
        """
        CREATE TABLE schema_version (version INTEGER NOT NULL);
        INSERT INTO schema_version VALUES (2);
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_path TEXT UNIQUE NOT NULL,
            project_name TEXT NOT NULL DEFAULT '',
            total_seconds INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            last_accessed TEXT NOT NULL
        );
        CREATE TABLE sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT,
            duration_seconds INTEGER NOT NULL DEFAULT 0,
            recovered INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE active_session (
            id INTEGER PRIMARY KEY,
            project_path TEXT NOT NULL,
            start_time TEXT NOT NULL,
            last_heartbeat TEXT NOT NULL,
            base_seconds INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE daily_totals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_date TEXT NOT NULL,
            project_id INTEGER NOT NULL,
            day_seconds INTEGER NOT NULL DEFAULT 0,
            UNIQUE (work_date, project_id)
        );
        INSERT INTO projects
            (project_path, project_name, total_seconds, created_at, last_accessed)
            VALUES ('/projetos/safra.qgz', 'Safra', 30, '2026-07-01', '2026-07-23');
        INSERT INTO sessions
            (project_id, start_time, end_time, duration_seconds, recovered)
            VALUES
            (1, '2026-07-01T10:00:00+00:00', '2026-07-01T10:02:00+00:00', 120, 0),
            (1, '2026-07-23T10:00:00+00:00', '2026-07-23T10:00:30+00:00', 30, 0);
        """
    )
    connection.commit()
    connection.close()

    database = PersistenceManager(str(profile))
    sessions = database.get_sessions("/projetos/safra.qgz")

    assert database._conn.execute("SELECT version FROM schema_version").fetchone()[
        "version"
    ] == 8
    backup_path = profile / "time_tracker.db.bak-v2"
    assert backup_path.is_file()
    backup = sqlite3.connect(backup_path)
    assert backup.execute("SELECT version FROM schema_version").fetchone()[0] == 2
    assert (
        backup.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='recovery_errors'"
        ).fetchone()
        is None
    )
    backup.close()
    assert [row["counts_toward_total"] for row in sessions] == [1, 0]
    database.delete_session(sessions[0]["id"])
    assert database.get_project_seconds("/projetos/safra.qgz") == 0
    database.close()


def test_equivalent_project_paths_share_the_same_record(tmp_path):
    database = PersistenceManager(str(tmp_path / "profile"))
    canonical = str(tmp_path / "projetos" / "safra.qgz")
    equivalent = str(tmp_path / "projetos" / "subpasta" / ".." / "safra.qgz")

    _record_session(database, equivalent, 25)

    assert normalize_project_path(equivalent) == normalize_project_path(canonical)
    assert database.get_project_seconds(canonical) == 25
    assert len(database.get_all_projects()) == 1
    database.close()


def test_windows_project_paths_are_case_and_separator_insensitive():
    first = normalize_project_path(r"C:\Projetos\Safra\mapa.qgz")
    second = normalize_project_path(r"c:/projetos/safra/.\mapa.qgz")

    assert first == second


def test_path_migration_merges_preexisting_equivalent_records(tmp_path):
    profile = tmp_path / "profile"
    database = PersistenceManager(str(profile))
    now = "2026-07-23T12:00:00+00:00"
    database._conn.executemany(
        "INSERT INTO projects "
        "(project_path, project_name, total_seconds, created_at, last_accessed) "
        "VALUES (?,?,?,?,?)",
        [
            ("/projetos/safra.qgz", "Safra", 20, now, now),
            ("/projetos/sub/../safra.qgz", "Safra duplicada", 10, now, now),
        ],
    )
    database._conn.execute("UPDATE schema_version SET version=5")
    database._conn.commit()
    database.close()

    migrated = PersistenceManager(str(profile))

    assert len(migrated.get_all_projects()) == 1
    assert migrated.get_project_seconds("/projetos/safra.qgz") == 30
    migrated.close()


class _TrackerDatabase:
    def __init__(self):
        self.updated = []
        self.completed = []
        self.started = []
        self.active_cleared = False
        self.migrations = []

    def begin_active_session(
        self, project_path, base_seconds, min_session_seconds=0
    ):
        assert project_path == "/projetos/safra.qgz"
        self.started.append(base_seconds)
        return "2026-07-23T12:00:00+00:00"

    def update_project_seconds(self, project_path, seconds, project_name):
        self.updated.append((project_path, seconds, project_name))

    def end_active_session(self, project_path, started_at, seconds):
        self.completed.append((project_path, started_at, seconds))

    def clear_active_session(self):
        self.active_cleared = True

    def get_today_seconds(self):
        return 0

    def get_project_seconds(self, _project_path):
        return 0

    def migrate_project_path(self, old_path, new_path, new_name):
        self.migrations.append((old_path, new_path, new_name))


class _TrackerConfiguration:
    idle_timeout_minutes = 0
    auto_start_on_open = False
    min_session_seconds = 0
    pause_on_focus_loss = False
    show_project_name = False
    show_daily_progress = False
    daily_goal_hours = 0
    notify_on_session_end = False
    confirm_on_reset = True


def test_tracker_start_pause_resume_and_stop(qgis_application, monkeypatch):
    from qgis_time_tracker.core import tracker as tracker_module

    database = _TrackerDatabase()
    tracker = TimeTracker(database, _TrackerConfiguration())
    tracker._project_key = "/projetos/safra.qgz"
    tracker._project_name = "Safra"
    clock = iter((100.0, 105.0, 110.0, 115.0, 120.0))
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: next(clock))

    tracker.start()
    assert tracker.state == TrackerState.RUNNING
    assert tracker.current_seconds() == 5
    tracker.pause()
    assert tracker.state == TrackerState.PAUSED
    assert tracker.current_seconds() == 10

    tracker.start()
    tracker.stop()

    assert tracker.state == TrackerState.STOPPED
    assert database.started == [0, 10]
    assert database.updated[-1] == ("/projetos/safra.qgz", 15, "Safra")
    assert database.completed[-1][-1] == 5


def test_tracker_discards_session_shorter_than_configured_minimum(
    qgis_application, monkeypatch
):
    from qgis_time_tracker.core import tracker as tracker_module

    database = _TrackerDatabase()
    configuration = _TrackerConfiguration()
    configuration.min_session_seconds = 60
    tracker = TimeTracker(database, configuration)
    tracker._project_key = "/projetos/safra.qgz"
    tracker._project_name = "Safra"
    clock = iter((100.0, 110.0))
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: next(clock))

    tracker.start()
    tracker.stop()

    assert tracker.state == TrackerState.STOPPED
    assert database.active_cleared is True
    assert database.updated == []
    assert database.completed == []


def test_idle_pause_commits_only_until_configured_threshold(
    qgis_application, monkeypatch
):
    from qgis_time_tracker.core import tracker as tracker_module

    database = _TrackerDatabase()
    configuration = _TrackerConfiguration()
    configuration.idle_timeout_minutes = 1
    tracker = TimeTracker(database, configuration)
    tracker._project_key = "/projetos/safra.qgz"
    tracker._project_name = "Safra"
    clock = iter((100.0, 195.0))
    monkeypatch.setattr(tracker_module.time, "monotonic", lambda: next(clock))

    tracker.start()
    tracker._last_activity_ts = 130.0
    tracker._check_idle()

    assert tracker.state == TrackerState.PAUSED
    assert tracker.pause_reason == "idle"
    assert database.completed[-1][-1] == 90


def test_save_as_does_not_move_history_from_saved_project(
    qgis_application, monkeypatch
):
    from qgis_time_tracker.core import tracker as tracker_module

    database = _TrackerDatabase()
    tracker = TimeTracker(database, _TrackerConfiguration())
    tracker._project_key = "/projetos/original.qgz"
    tracker._project_name = "Original"
    monkeypatch.setattr(tracker_module, "_current_project_name", lambda: "Cópia")

    tracker.on_project_saved("/projetos/copia.qgz")

    assert database.migrations == []
    assert tracker.project_key == "/projetos/copia.qgz"
    assert tracker.project_name == "Cópia"


def test_new_unsaved_projects_receive_distinct_keys(qgis_application):
    from qgis.core import QgsProject

    QgsProject.instance().clear()
    tracker = TimeTracker(_TrackerDatabase(), _TrackerConfiguration())

    tracker.load_project(force_new_unsaved=True)
    first_key = tracker.project_key
    tracker.load_project(force_new_unsaved=True)

    assert first_key.startswith("__unsaved__:")
    assert tracker.project_key.startswith("__unsaved__:")
    assert tracker.project_key != first_key


def test_toolbar_uses_portuguese_labels_and_standard_icons(qgis_application):
    from qgis_time_tracker.ui.toolbar_widget import TrackerWidget

    database = _TrackerDatabase()
    tracker = TimeTracker(database, _TrackerConfiguration())
    tracker._project_key = "/projetos/safra.qgz"
    tracker._project_name = "Safra"

    widget = TrackerWidget(tracker, database, _TrackerConfiguration())

    assert widget._btn_toggle.toolTip().startswith("Iniciar")
    assert widget._btn_stop.toolTip() == "Encerrar sessão"
    assert not widget._btn_toggle.icon().isNull()
    assert not widget._btn_stop.icon().isNull()

    tracker._state = TrackerState.PAUSED
    tracker._pause_reason = "idle"
    widget._apply_state(TrackerState.PAUSED)
    assert widget._status_lbl.text() == "Pausa: inatividade"
    widget.deleteLater()


def test_statistics_items_sort_by_numeric_value(qgis_application):
    from qgis_time_tracker.ui.stats_dialog import _SortItem

    short = _SortItem("99:00:00", 99 * 3600)
    long = _SortItem("100:00:00", 100 * 3600)

    assert short < long


def test_focus_filter_ignores_internal_window_changes(qgis_application):
    from qgis_time_tracker import time_tracker_plugin

    class Tracker:
        state = TrackerState.RUNNING
        pauses = []

        def pause(self, reason="manual"):
            self.pauses.append(reason)

    class Configuration:
        pause_on_focus_loss = True

    class Event:
        def __init__(self, event_type):
            self._event_type = event_type

        def type(self):
            return self._event_type

    tracker = Tracker()
    event_filter = time_tracker_plugin._WindowFilter(tracker, Configuration())
    window_event = next(iter(time_tracker_plugin._ev("WindowDeactivate")))
    application_event = next(iter(time_tracker_plugin._ev("ApplicationDeactivate")))

    event_filter.eventFilter(None, Event(window_event))
    assert tracker.pauses == []

    event_filter.eventFilter(None, Event(application_event))
    assert tracker.pauses == ["focus"]


def test_numeric_settings_are_clamped(monkeypatch):
    from qgis_time_tracker.core import settings as settings_module

    values = {
        "idle_timeout_minutes": 9999,
        "min_session_seconds": -10,
        "daily_goal_hours": 99,
    }
    monkeypatch.setattr(settings_module, "_get", values.get)
    settings = settings_module.TrackerSettings()

    assert settings.idle_timeout_minutes == 480
    assert settings.min_session_seconds == 0
    assert settings.daily_goal_hours == 16


class _PluginPersistence:
    def __init__(self):
        self.closed = False

    def get_project_seconds(self, _project_key):
        return 0

    def get_today_seconds(self):
        return 0

    def consume_recovery_errors(self):
        return []

    def close(self):
        self.closed = True


class _PluginInterface:
    def __init__(self):
        from qgis.PyQt.QtWidgets import QMainWindow

        self.window = QMainWindow()

    def mainWindow(self):
        return self.window

    def addToolBar(self, name):
        from qgis.PyQt.QtWidgets import QToolBar

        toolbar = QToolBar(name, self.window)
        self.window.addToolBar(toolbar)
        return toolbar


def test_plugin_lifecycle_removes_toolbar_filters_and_database(
    qgis_application, monkeypatch
):
    from qgis_time_tracker import time_tracker_plugin

    monkeypatch.setattr(
        time_tracker_plugin, "PersistenceManager", _PluginPersistence
    )
    plugin = time_tracker_plugin.TimeTrackerPlugin(_PluginInterface())

    plugin.initGui()
    database = plugin._db
    plugin.open_tool()
    plugin._on_cleared()

    assert plugin._toolbar.objectName() == "TimeTrackerToolBar"
    assert plugin._widget is not None
    assert plugin._tracker.project_key.startswith("__unsaved__:")
    plugin.unload()
    assert plugin._toolbar is None
    assert plugin._widget is None
    assert plugin._tracker is None
    assert plugin._act_filter is None
    assert plugin._win_filter is None
    assert database.closed is True
