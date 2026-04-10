"""
TimeTrackerPlugin – QGIS plugin entry point.

Lifecycle
---------
initGui()  → create DB, tracker, toolbar widget; install event filters;
             connect project signals; call load_project().
unload()   → stop tracker (flush to DB), remove filters, disconnect signals,
             remove toolbar, close DB connection.

Project signals used
--------------------
readProject  – fires after a .qgs/.qgz has been read.
writeProject – fires after Save/Save-As; used to migrate __unsaved__ time.
cleared      – fires when the user opens a new empty project.
"""

import os

from qgis.PyQt.QtCore import QObject, QEvent
from qgis.PyQt.QtWidgets import QApplication
from qgis.core import QgsProject

from .core.settings    import TrackerSettings
from .core.persistence import PersistenceManager
from .core.tracker     import TimeTracker, TrackerState, _current_project_name
from .ui.toolbar_widget import TrackerWidget


# ── event filters ─────────────────────────────────────────────────────────────

class _ActivityFilter(QObject):
    """
    Installed on QApplication to detect user activity.
    Forwards any mouse/keyboard event to tracker.record_activity()
    so the idle timer is reset correctly.  Never consumes events.
    """

    _WATCHED = frozenset({
        QEvent.MouseMove,
        QEvent.MouseButtonPress,
        QEvent.KeyPress,
        QEvent.Wheel,
        QEvent.TabletMove,
    })

    def __init__(self, tracker, parent=None):
        super().__init__(parent)
        self._t = tracker

    def eventFilter(self, obj, event):
        if event.type() in self._WATCHED:
            self._t.record_activity()
        return False


class _WindowFilter(QObject):
    """
    Installed on iface.mainWindow().
    Triggers auto-pause when QGIS is minimised or loses focus
    (only if the user has enabled pause_on_focus_loss in settings).
    """

    def __init__(self, tracker, settings, parent=None):
        super().__init__(parent)
        self._t   = tracker
        self._cfg = settings

    def eventFilter(self, obj, event):
        if self._cfg.pause_on_focus_loss:
            if event.type() == QEvent.WindowDeactivate:
                if self._t.state == TrackerState.RUNNING:
                    self._t.pause()
        return False


# ── plugin ────────────────────────────────────────────────────────────────────

class TimeTrackerPlugin:

    def __init__(self, iface):
        self._iface          = iface
        self._toolbar        = None
        self._widget         = None
        self._tracker        = None
        self._db             = None
        self._cfg            = None
        self._act_filter     = None
        self._win_filter     = None

    # ── QGIS lifecycle ────────────────────────────────────────────────────────

    def initGui(self):
        self._cfg     = TrackerSettings()
        self._db      = PersistenceManager()           # crash-recovery runs here
        self._tracker = TimeTracker(self._db, self._cfg)

        # toolbar
        self._toolbar = self._iface.addToolBar("Time Tracker")
        self._toolbar.setObjectName("TimeTrackerToolBar")
        self._widget  = TrackerWidget(self._tracker, self._db, self._cfg)
        self._toolbar.addWidget(self._widget)

        # event filters
        self._act_filter = _ActivityFilter(self._tracker)
        QApplication.instance().installEventFilter(self._act_filter)

        self._win_filter = _WindowFilter(self._tracker, self._cfg)
        self._iface.mainWindow().installEventFilter(self._win_filter)

        # project signals
        proj = QgsProject.instance()
        proj.readProject.connect(self._on_read)
        proj.writeProject.connect(self._on_write)
        proj.cleared.connect(self._on_cleared)

        # load whatever project is already open (if plugin is activated mid-session)
        self._tracker.load_project()

    def unload(self):
        if self._tracker:
            self._tracker.stop()

        if self._act_filter:
            QApplication.instance().removeEventFilter(self._act_filter)
            self._act_filter = None

        if self._win_filter:
            self._iface.mainWindow().removeEventFilter(self._win_filter)
            self._win_filter = None

        proj = QgsProject.instance()
        for sig, slot in [
            (proj.readProject,  self._on_read),
            (proj.writeProject, self._on_write),
            (proj.cleared,      self._on_cleared),
        ]:
            try:
                sig.disconnect(slot)
            except Exception:
                pass

        if self._toolbar:
            self._iface.mainWindow().removeToolBar(self._toolbar)
            self._toolbar = None

        if self._db:
            self._db.close()
            self._db = None

    # ── project signal handlers ───────────────────────────────────────────────

    def _on_read(self, doc=None):
        """New project loaded from disk."""
        self._tracker.load_project()

    def _on_write(self, doc=None):
        """
        Called after every Save/Save-As.

        If the tracker was following an __unsaved__ project that now has a
        real path, migrate the accumulated time to the new key so it is not
        lost.
        """
        new_key = QgsProject.instance().absoluteFilePath()
        if not new_key:
            return
        old_key = self._tracker.project_key
        if old_key and old_key != new_key:
            was_running = self._tracker.state == TrackerState.RUNNING
            if was_running:
                self._tracker.pause()

            new_name = _current_project_name()
            self._db.migrate_project_path(old_key, new_key, new_name)

            # Update tracker internals without triggering a full load
            self._tracker._project_key  = new_key
            self._tracker._project_name = new_name
            self._tracker._base_seconds = self._db.get_project_seconds(new_key)
            self._tracker.time_updated.emit(self._tracker._base_seconds)

            if was_running:
                self._tracker.start()

    def _on_cleared(self):
        """User opened a new empty project."""
        if self._tracker.state != TrackerState.STOPPED:
            self._tracker.stop()
        # Reset display to zero without a project
        self._tracker._project_key  = None
        self._tracker._project_name = None
        self._tracker._base_seconds = 0
        self._tracker.time_updated.emit(0)
        self._tracker.state_changed.emit(TrackerState.STOPPED.value)