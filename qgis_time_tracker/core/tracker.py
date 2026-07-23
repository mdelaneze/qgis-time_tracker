"""
TimeTracker – three-state machine (STOPPED → RUNNING ⇄ PAUSED → STOPPED).


Heartbeat (every 5 s): updates active_session.last_heartbeat so QGIS crashes
lose at most 5 s.  The heartbeat does NOT touch projects.total_seconds; that
write is deferred to pause()/stop()/_commit_running() so the DB is not hammered
every 5 s during long sessions.
"""

import os
import time
import uuid
from enum import Enum

from qgis.core import QgsProject
from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal

from .persistence import normalize_project_path


class TrackerState(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


# ── module-level helpers ───────────────────────────────────────────────────────


def _current_project_name() -> str:
    title = QgsProject.instance().title()
    if title:
        return title
    path = QgsProject.instance().absoluteFilePath()
    if path:
        return os.path.splitext(os.path.basename(path))[0]
    return "Projeto não salvo"


# ── main class ─────────────────────────────────────────────────────────────────


class TimeTracker(QObject):
    """
    Signals
    -------
    time_updated(int)       – emitted every second while RUNNING; value is the
                              current total accumulated seconds for the active project.
    state_changed(str)      – emitted on every state transition.
    project_changed(str)    – emitted when a new project is loaded.
    settings_changed()      – emitted after SettingsDialog saves new settings so
                              toolbar UI can refresh.
    session_completed(int)  – emitted at the end of every tracked session with
                              the session duration in seconds.
    daily_updated(int)      – emitted every minute while RUNNING with today's
                              total seconds across all projects; used by progress bar.
    """

    time_updated = pyqtSignal(int)
    state_changed = pyqtSignal(str)
    project_changed = pyqtSignal(str)
    settings_changed = pyqtSignal()
    session_completed = pyqtSignal(int)
    daily_updated = pyqtSignal(int)

    # ── construction ──────────────────────────────────────────────────────────

    def __init__(self, persistence, settings, parent=None):
        super().__init__(parent)
        self._db = persistence
        self._cfg = settings

        self._state = TrackerState.STOPPED
        self._base_seconds = 0
        self._session_start_ts = None
        self._session_start_iso = None
        self._project_key = None
        self._project_name = None
        self._unsaved_key = None
        self._pause_reason = None
        self._daily_tick_count = 0  # counts 1-s ticks; emits daily_updated every 60

        self._display_timer = QTimer(self)
        self._display_timer.setInterval(1000)
        self._display_timer.timeout.connect(self._tick)

        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(5000)
        self._heartbeat_timer.timeout.connect(self._heartbeat)

        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(10_000)
        self._idle_timer.timeout.connect(self._check_idle)

        self._last_activity_ts = time.monotonic()

    # ── public properties ─────────────────────────────────────────────────────

    @property
    def state(self) -> TrackerState:
        return self._state

    @property
    def project_key(self) -> str:
        return self._project_key

    @property
    def project_name(self) -> str:
        return self._project_name or ""

    @property
    def pause_reason(self) -> str:
        return self._pause_reason or ""

    # ── public API ────────────────────────────────────────────────────────────

    def load_project(self, force_new_unsaved: bool = False):
        """
        Called when QGIS opens a project or the plugin initialises.
        Saves and stops the current session (if any), then loads the new
        project's accumulated time.
        """
        path = QgsProject.instance().absoluteFilePath()
        if path:
            key = normalize_project_path(path)
        else:
            if force_new_unsaved or self._unsaved_key is None:
                self._unsaved_key = f"__unsaved__:{uuid.uuid4().hex}"
            key = self._unsaved_key
        if key == self._project_key:
            new_name = _current_project_name()
            if new_name != self._project_name:
                self._project_name = new_name
                self.project_changed.emit(self._project_name)
            return

        if self._state == TrackerState.RUNNING:
            self._commit_running()
        self._stop_timers()

        self._project_key = key
        self._project_name = _current_project_name()
        self._base_seconds = self._db.get_project_seconds(key)
        self._state = TrackerState.STOPPED
        self._pause_reason = None
        self._daily_tick_count = 0

        self.state_changed.emit(self._state.value)
        self.time_updated.emit(self._base_seconds)
        self.project_changed.emit(self._project_name)

        if self._cfg.auto_start_on_open:
            self.start()

    def on_project_saved(self, new_path: str):
        """Atualiza o projeto após salvar, sem transferir histórico em Salvar como."""
        new_path = normalize_project_path(new_path)
        if not new_path or new_path == self._project_key:
            return

        old_key = self._project_key
        was_running = self._state == TrackerState.RUNNING
        if was_running:
            self.pause()

        new_name = _current_project_name()
        if old_key and old_key.startswith("__unsaved__"):
            self._db.migrate_project_path(old_key, new_path, new_name)
        self._project_key = new_path
        self._project_name = new_name
        self._base_seconds = self._db.get_project_seconds(new_path)
        self.time_updated.emit(self._base_seconds)
        self.project_changed.emit(self._project_name)
        if was_running:
            self.start()

    def start(self):
        if self._state == TrackerState.RUNNING:
            return
        if not self._project_key:
            self.load_project()

        now = time.monotonic()
        self._last_activity_ts = now
        self._session_start_ts = now
        self._session_start_iso = self._db.begin_active_session(
            self._project_key,
            self._base_seconds,
            max(0, int(getattr(self._cfg, "min_session_seconds", 0))),
        )

        self._state = TrackerState.RUNNING
        self._pause_reason = None
        self._display_timer.start()
        self._heartbeat_timer.start()

        if self._cfg.idle_timeout_minutes > 0:
            self._idle_timer.start()

        self.state_changed.emit(self._state.value)

    def pause(self, reason: str = "manual", effective_elapsed: int = None):
        if self._state != TrackerState.RUNNING:
            return

        self._commit_running(effective_elapsed)
        self._state = TrackerState.PAUSED
        self._pause_reason = reason
        self._stop_timers()

        self.state_changed.emit(self._state.value)
        self.time_updated.emit(self._base_seconds)

    def stop(self):
        if self._state == TrackerState.STOPPED:
            return

        if self._state == TrackerState.RUNNING:
            self._commit_running()
        else:
            self._db.clear_active_session()

        self._state = TrackerState.STOPPED
        self._pause_reason = None
        self._stop_timers()

        self.state_changed.emit(self._state.value)
        self.time_updated.emit(self._base_seconds)

    def toggle(self):
        if self._state == TrackerState.RUNNING:
            self.pause()
        else:
            self.start()

    def reset(self):
        """Stop tracking and zero out the current project's accumulated time."""
        self.stop()
        if self._project_key:
            self._base_seconds = 0
            self._db.reset_project_seconds(self._project_key)
            self.time_updated.emit(0)

    def apply_idle_setting(self):
        if self._cfg.idle_timeout_minutes > 0 and self._state == TrackerState.RUNNING:
            self._idle_timer.start()
        else:
            self._idle_timer.stop()

    def apply_project_name_setting(self):
        self.settings_changed.emit()

    def sync_base_seconds(self):
        """
        Re-read base_seconds from DB for the current project and refresh
        the toolbar display. Only effective when STOPPED.
        """
        if self._state != TrackerState.STOPPED or not self._project_key:
            return
        self._base_seconds = self._db.get_project_seconds(self._project_key)
        self.time_updated.emit(self._base_seconds)

    def record_activity(self):
        self._last_activity_ts = time.monotonic()

    def current_seconds(self) -> int:
        if self._state == TrackerState.RUNNING and self._session_start_ts is not None:
            return self._base_seconds + int(time.monotonic() - self._session_start_ts)
        return self._base_seconds

    def running_elapsed_seconds(self) -> int:
        if self._state == TrackerState.RUNNING and self._session_start_ts is not None:
            return max(0, int(time.monotonic() - self._session_start_ts))
        return 0

    def today_seconds(self) -> int:
        """Total seconds tracked today (all projects) from DB + live session."""
        db_today = self._db.get_today_seconds()
        elapsed = self.running_elapsed_seconds()
        if elapsed and self._session_start_iso:
            db_today += self._db.live_today_seconds(self._session_start_iso, elapsed)
        return db_today

    def current_week_seconds(self) -> int:
        total = self._db.get_current_week_seconds()
        elapsed = self.running_elapsed_seconds()
        if elapsed and self._session_start_iso:
            total += self._db.live_current_week_seconds(
                self._session_start_iso, elapsed
            )
        return total

    # ── private helpers ───────────────────────────────────────────────────────

    def _commit_running(self, effective_elapsed: int = None):
        elapsed = (
            self.running_elapsed_seconds()
            if effective_elapsed is None
            else max(0, int(effective_elapsed))
        )
        min_secs = max(0, int(getattr(self._cfg, "min_session_seconds", 0)))
        if elapsed < min_secs:
            self._db.clear_active_session()
            self._session_start_ts = None
            self._session_start_iso = None
            self._daily_tick_count = 0
            return

        self._base_seconds += elapsed
        self._db.update_project_seconds(
            self._project_key, self._base_seconds, self._project_name
        )
        self._db.end_active_session(self._project_key, self._session_start_iso, elapsed)
        self._session_start_ts = None
        self._session_start_iso = None
        self._daily_tick_count = 0

        if elapsed > 0:
            self.session_completed.emit(elapsed)

    def _stop_timers(self):
        self._display_timer.stop()
        self._heartbeat_timer.stop()
        self._idle_timer.stop()

    def _tick(self):
        self.time_updated.emit(self.current_seconds())
        self._daily_tick_count += 1
        if self._daily_tick_count >= 60:
            self._daily_tick_count = 0
            self.daily_updated.emit(self.today_seconds())

    def _heartbeat(self):
        self._db.update_heartbeat()

    def _check_idle(self):
        timeout_secs = self._cfg.idle_timeout_minutes * 60
        if timeout_secs > 0:
            idle_for = time.monotonic() - self._last_activity_ts
            if idle_for >= timeout_secs:
                effective_elapsed = (
                    self._last_activity_ts
                    + timeout_secs
                    - self._session_start_ts
                )
                self.pause(reason="idle", effective_elapsed=int(effective_elapsed))
