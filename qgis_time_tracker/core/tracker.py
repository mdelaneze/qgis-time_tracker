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


# ── module-level helpers (read current QGIS project info) ─────────────────────

def _current_project_key() -> str:
    path = QgsProject.instance().absoluteFilePath()
    return path if path else "__unsaved__"


def _current_project_name() -> str:
    title = QgsProject.instance().title()
    if title:
        return title
    import os
    path = QgsProject.instance().absoluteFilePath()
    if path:
        return os.path.splitext(os.path.basename(path))[0]
    return "Unsaved Project"


# ── main class ─────────────────────────────────────────────────────────────────

class TimeTracker(QObject):
    """
    Signals
    -------
    time_updated(int)   – emitted every second while RUNNING; value is current
                          total accumulated seconds for the active project.
    state_changed(str)  – emitted on every state transition; value is
                          TrackerState.value ("stopped" | "running" | "paused").
    """

    time_updated  = pyqtSignal(int)
    state_changed = pyqtSignal(str)

    # ── construction ──────────────────────────────────────────────────────────

    def __init__(self, persistence, settings, parent=None):
        super().__init__(parent)
        self._db  = persistence
        self._cfg = settings

        self._state             = TrackerState.STOPPED
        self._base_seconds      = 0          # seconds accumulated in previous sessions
        self._session_start_ts  = None       # time.monotonic() at session start
        self._session_start_iso = None       # UTC ISO str returned by DB (for session log)
        self._project_key       = None
        self._project_name      = None

        # 1-second display refresh
        self._display_timer = QTimer(self)
        self._display_timer.setInterval(1000)
        self._display_timer.timeout.connect(self._tick)

        # 5-second crash-guard heartbeat
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(5000)
        self._heartbeat_timer.timeout.connect(self._heartbeat)

        # Idle-detection poll (10 s intervals)
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(10_000)
        self._idle_timer.timeout.connect(self._check_idle)

        self._last_activity_ts = time.monotonic()

    # ── public API ────────────────────────────────────────────────────────────

    def load_project(self):
        """
        Called when QGIS opens a project or the plugin initialises.
        Saves and stops the current session (if any), then loads the new
        project's accumulated time.
        """
        key = _current_project_key()
        if key == self._project_key:
            return  # same project – nothing to do

        if self._state == TrackerState.RUNNING:
            self._commit_running()
        # PAUSED: base_seconds is already correct; no DB write needed here
        self._stop_timers()

        self._project_key  = key
        self._project_name = _current_project_name()
        self._base_seconds = self._db.get_project_seconds(key)
        self._state        = TrackerState.STOPPED

        self.state_changed.emit(self._state.value)
        self.time_updated.emit(self._base_seconds)

        if self._cfg.auto_start_on_open:
            self.start()

    def start(self):
        if self._state == TrackerState.RUNNING:
            return

        # validação de projeto
        if not self._project_key or self._project_key == "__unsaved__":
            if not getattr(self, "_warned_no_project", False):
                try:
                    # tenta usar message bar (mais elegante)
                    iface.messageBar().pushWarning(
                        "Time Tracker",
                        "Save or open a project to start tracking."
                    )
                except Exception:
                    # fallback para popup clássico
                    QMessageBox.warning(
                        None,
                        "Time Tracker",
                        "You need to save or open a QGIS project before starting time tracking."
                    )
                self._warned_no_project = True
            return
        else:
            # reset do flag quando estiver tudo ok
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
        """
        Stop tracking and register session time. It not resets the accumulated time 
        for the project (use reset() for that).
        """
        if self._state == TrackerState.STOPPED:
            return

        if self._state == TrackerState.RUNNING:
            self._commit_running()
        else:
            # PAUSED: active_session já foi limpo no start anterior
            self._db.clear_active_session()

        self._state = TrackerState.STOPPED
        self._stop_timers()

        self.state_changed.emit(self._state.value)
        self.time_updated.emit(self._base_seconds)


    def reset(self):
        """Stop and zero out the current project's accumulated time."""
        self.stop()

        if self._project_key:
            self._base_seconds = 0
            self._db.reset_project_seconds(self._project_key)
            self.time_updated.emit(0)

    def record_activity(self):
        """Called by the application-level event filter on mouse/key events."""
        self._last_activity_ts = time.monotonic()

    def current_seconds(self) -> int:
        if self._state == TrackerState.RUNNING and self._session_start_ts is not None:
            return self._base_seconds + int(
                time.monotonic() - self._session_start_ts
            )
        return self._base_seconds

    @property
    def state(self) -> TrackerState:
        return self._state

    @property
    def project_key(self):
        return self._project_key

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