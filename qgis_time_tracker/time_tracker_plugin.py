"""
TimeTrackerPlugin – QGIS 4 / Qt 6 entry point.

Qt 6 migration notes
--------------------
* QEvent.Type enum members are accessed as QEvent.Type.MouseMove etc. in
  PyQt6, but PyQt5 exposes them as QEvent.MouseMove.  To support BOTH
  Qt5 (QGIS 3.x) and Qt6 (QGIS 4.x) we resolve enum values at import time
  via _qt_event() so the same code runs on either stack.
* All other APIs used here (QObject, QApplication, QgsProject) are
  identical between Qt5 and Qt6.

Lifecycle
---------
initGui()  → create DB, tracker, toolbar widget; install event filters;
             connect project signals; call load_project().
unload()   → stop tracker (flush to DB), remove filters, disconnect signals,
             remove toolbar, close DB connection.

Project signals
---------------
readProject  – fires after a .qgs/.qgz has been read.
writeProject – fires after Save/Save-As; used to migrate __unsaved__ time.
cleared      – fires when the user opens a new empty project.
"""

import os

from qgis.core import QgsProject
from qgis.PyQt.QtCore import QEvent, QObject
from qgis.PyQt.QtWidgets import QApplication

from .core.persistence import PersistenceManager
from .core.settings import TrackerSettings
from .core.tracker import TimeTracker, TrackerState, _current_project_name
from .ui.toolbar_widget import TrackerWidget

# ── Qt5 / Qt6 event-type compat ───────────────────────────────────────────────


def _ev(*names):
    """
    Resolve QEvent enum members for both PyQt5 (QEvent.MouseMove) and
    PyQt6 (QEvent.Type.MouseMove).  Falls back gracefully if a name is
    unavailable on the current Qt version.
    """
    results = set()
    for name in names:
        # PyQt6 style
        t = getattr(getattr(QEvent, "Type", None), name, None)
        if t is not None:
            results.add(t)
            continue
        # PyQt5 style
        t = getattr(QEvent, name, None)
        if t is not None:
            results.add(t)
    return frozenset(results)


# ── event filters ─────────────────────────────────────────────────────────────


class _ActivityFilter(QObject):
    """
    Installed on QApplication to detect user activity.
    Forwards any mouse/keyboard event to tracker.record_activity()
    so the idle timer is reset correctly.  Never consumes events.
    """

    _WATCHED = _ev("MouseMove", "MouseButtonPress", "KeyPress", "Wheel", "TabletMove")

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

    _DEACTIVATE = _ev("WindowDeactivate")

    def __init__(self, tracker, settings, parent=None):
        super().__init__(parent)
        self._t = tracker
        self._cfg = settings

    def eventFilter(self, obj, event):
        if self._cfg.pause_on_focus_loss:
            if event.type() in self._DEACTIVATE:
                if self._t.state == TrackerState.RUNNING:
                    self._t.pause()
        return False


# ── plugin ────────────────────────────────────────────────────────────────────


class TimeTrackerPlugin:

    def __init__(self, iface):
        self._iface = iface
        self._toolbar = None
        self._widget = None
        self._tracker = None
        self._db = None
        self._cfg = None
        self._act_filter = None
        self._win_filter = None

    # ── QGIS lifecycle ────────────────────────────────────────────────────────

    def initGui(self):
        self._cfg = TrackerSettings()
        self._db = PersistenceManager()  # crash-recovery runs here
        self._tracker = TimeTracker(self._db, self._cfg)

        # toolbar
        self._toolbar = self._iface.addToolBar("Time Tracker")
        self._toolbar.setObjectName("TimeTrackerToolBar")
        self._widget = TrackerWidget(self._tracker, self._db, self._cfg)
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
            (proj.readProject, self._on_read),
            (proj.writeProject, self._on_write),
            (proj.cleared, self._on_cleared),
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
        self._tracker.load_project()

    def _on_write(self, doc=None):
        """
        Called after every Save/Save-As.
        If the tracker was following an __unsaved__ project that now has a
        real path, migrate the accumulated time to the new key.
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

            self._tracker._project_key = new_key
            self._tracker._project_name = new_name
            self._tracker._base_seconds = self._db.get_project_seconds(new_key)
            self._tracker.time_updated.emit(self._tracker._base_seconds)

            if was_running:
                self._tracker.start()

    def _on_cleared(self):
        if self._tracker.state != TrackerState.STOPPED:
            self._tracker.stop()
        self._tracker._project_key = None
        self._tracker._project_name = None
        self._tracker._base_seconds = 0
        self._tracker.time_updated.emit(0)
        self._tracker.state_changed.emit(TrackerState.STOPPED.value)
