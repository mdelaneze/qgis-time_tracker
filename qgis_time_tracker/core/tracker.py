"""
TimeTracker – three-state machine (STOPPED → RUNNING ⇄ PAUSED → STOPPED).

All timing uses time.monotonic() to be immune to system clock changes (NTP
adjustments, timezone switches, DST). The ISO timestamp stored for sessions
comes from the persistence layer which uses UTC wall-clock — that is fine
because it is only used for display/export, never for duration arithmetic.

Timers run only on the Qt main thread so there are no threading concerns.

Heartbeat (every 5 s): updates active_session.last_heartbeat so QGIS crashes
lose at most 5 s.  The heartbeat does NOT touch projects.total_seconds; that
write is deferred to pause()/stop()/_commit_running() so the DB is not hammered
every 5 s during long sessions.
"""

import os
import time
from enum import Enum

from qgis.PyQt.QtCore import QObject, QTimer, pyqtSignal
from qgis.core import QgsProject
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.utils import iface


class TrackerState(Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED  = "paused"


# ── module-level helpers ───────────────────────────────────────────────────────

def _current_project_key() -> str:
    path = QgsProject.instance().absoluteFilePath()
    return path if path else "__unsaved__"


def _current_project_name() -> str:
    title = QgsProject.instance().title()
    if title:
        return title
    path = QgsProject.instance().absoluteFilePath()
    if path:
        return os.path.splitext(os.path.basename(path))[0]
    return "Unsaved Project"


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
                              toolbar UI can refresh (e.g. show/hide project label).
    session_completed(int)  – emitted at the end of every tracked session with
                              the session duration in seconds. Useful for
                              notifications and per-session stats.
    """

    time_updated      = pyqtSignal(int)
    state_changed     = pyqtSignal(str)
    project_changed   = pyqtSignal(str)
    settings_changed  = pyqtSignal()
    session_completed = pyqtSignal(int)   # NEW: duration in seconds

    # ── construction ──────────────────────────────────────────────────────────

    def __init__(self, persistence, settings, parent=None):
        super().__init__(parent)
        self._db  = persistence
        self._cfg = settings

        self._state             = TrackerState.STOPPED
        self._base_seconds      = 0
        self._session_start_ts  = None
        self._session_start_iso = None
        self._project_key       = None
        self._project_name      = None
        self._warned_no_project = False

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

    # ── public API ────────────────────────────────────────────────────────────

    def load_project(self):
        """
        Called when QGIS opens a project or the plugin initialises.
        Saves and stops the current session (if any), then loads the new
        project\'s accumulated time.
        """
        key = _current_project_key()
        if key == self._project_key:
            new_name = _current_project_name()
            if new_name != self._project_name:
                self._project_name = new_name
                self.project_changed.emit(self._project_name)
            return

        if self._state == TrackerState.RUNNING:
            self._commit_running()
        self._stop_timers()

        self._project_key  = key
        self._project_name = _current_project_name()
        self._base_seconds = self._db.get_project_seconds(key)
        self._state        = TrackerState.STOPPED
        self._warned_no_project = False

        self.state_changed.emit(self._state.value)
        self.time_updated.emit(self._base_seconds)
        self.project_changed.emit(self._project_name)

        if self._cfg.auto_start_on_open:
            self.start()

    def on_project_saved(self, new_path: str):
        """
        Call when QgsProject.fileNameChanged fires (i.e. the user saves a new
        project for the first time or uses "Save As").
        """
        if not new_path or new_path == self._project_key:
            return

        old_key  = self._project_key or "__unsaved__"
        new_name = os.path.splitext(os.path.basename(new_path))[0] or new_path

        self._db.migrate_project_path(old_key, new_path, new_name)

        self._project_key  = new_path
        self._project_name = new_name

        if self._state == TrackerState.RUNNING:
            self._db.update_active_session_path(new_path)

        self.project_changed.emit(self._project_name)

    def start(self):
        if self._state == TrackerState.RUNNING:
            return

        self._warned_no_project = False
        self._session_start_ts  = time.monotonic()
        self._session_start_iso = self._db.begin_active_session(
            self._project_key, self._base_seconds
        )

        self._state = TrackerState.RUNNING
        self._display_timer.start()
        self._heartbeat_timer.start()

        if self._cfg.idle_timeout_minutes > 0:
            self._idle_timer.start()

        self.state_changed.emit(self._state.value)

    def pause(self):
        if self._state != TrackerState.RUNNING:
            return

        self._commit_running()
        self._state = TrackerState.PAUSED
        self._stop_timers()

        self.state_changed.emit(self._state.value)
        self.time_updated.emit(self._base_seconds)

    def stop(self):
        """Stop tracking. Does NOT reset the accumulated counter."""
        if self._state == TrackerState.STOPPED:
            return

        if self._state == TrackerState.RUNNING:
            self._commit_running()
        else:
            self._db.clear_active_session()

        self._state = TrackerState.STOPPED
        self._stop_timers()

        self.state_changed.emit(self._state.value)
        self.time_updated.emit(self._base_seconds)

    def toggle(self):
        """
        Start if STOPPED or PAUSED; pause if RUNNING.
        Single-method convenience used by keyboard shortcuts and toolbar toggle.
        """
        if self._state == TrackerState.RUNNING:
            self.pause()
        else:
            self.start()

    def reset(self):
        """Stop tracking and zero out the current project\'s accumulated time."""
        self.stop()
        if self._project_key:
            self._base_seconds = 0
            self._db.reset_project_seconds(self._project_key)
            self.time_updated.emit(0)

    def apply_idle_setting(self):
        """
        Apply the current idle_timeout_minutes value without restarting the
        tracker. Called by SettingsDialog after the user confirms new settings.
        """
        if self._cfg.idle_timeout_minutes > 0 and self._state == TrackerState.RUNNING:
            self._idle_timer.start()
        else:
            self._idle_timer.stop()

    def apply_project_name_setting(self):
        """Notify toolbar to refresh show_project_name visibility."""
        self.settings_changed.emit()

    def sync_base_seconds(self):
        """
        Re-read base_seconds from DB for the current project and refresh
        the toolbar display. Only effective when STOPPED.
        Called by StatsDialog after external DB writes that change total_seconds.
        """
        if self._state != TrackerState.STOPPED or not self._project_key:
            return
        self._base_seconds = self._db.get_project_seconds(self._project_key)
        self.time_updated.emit(self._base_seconds)

    def record_activity(self):
        """Called by the application-level event filter on mouse/key events."""
        self._last_activity_ts = time.monotonic()

    def current_seconds(self) -> int:
        if self._state == TrackerState.RUNNING and self._session_start_ts is not None:
            return self._base_seconds + int(
                time.monotonic() - self._session_start_ts
            )
        return self._base_seconds

    # ── private helpers ───────────────────────────────────────────────────────

    def _commit_running(self):
        """
        Flush elapsed time to DB and close the active_session sentinel.
        Must only be called when state == RUNNING.
        """
        elapsed = int(time.monotonic() - self._session_start_ts)
        self._base_seconds += elapsed
        self._db.update_project_seconds(
            self._project_key, self._base_seconds, self._project_name
        )
        self._db.end_active_session(
            self._project_key, self._session_start_iso, elapsed
        )
        self._session_start_ts  = None
        self._session_start_iso = None

        # Notify listeners (e.g. toolbar notification, stats refresh)
        # Only emits for sessions with meaningful duration (> cfg.min_session_seconds)
        min_secs = getattr(self._cfg, "min_session_seconds", 0)
        if elapsed > min_secs:
            self.session_completed.emit(elapsed)

    def _stop_timers(self):
        self._display_timer.stop()
        self._heartbeat_timer.stop()
        self._idle_timer.stop()

    def _tick(self):
        self.time_updated.emit(self.current_seconds())

    def _heartbeat(self):
        self._db.update_heartbeat()

    def _check_idle(self):
        timeout_secs = self._cfg.idle_timeout_minutes * 60
        if timeout_secs > 0:
            idle_for = time.monotonic() - self._last_activity_ts
            if idle_for >= timeout_secs:
                self.pause()