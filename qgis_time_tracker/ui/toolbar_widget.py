"""
TrackerWidget – compact toolbar strip.


Keyboard shortcut
-----------------
  Ctrl+Alt+T  – toggle (start/pause)  — ApplicationShortcut, works
                even when the toolbar widget does not have focus.
"""

from qgis.PyQt.QtCore import QPoint, Qt
from qgis.PyQt.QtGui import QFont, QFontDatabase, QFontMetrics, QKeySequence
from qgis.PyQt.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)
from qgis.utils import iface

from ..core.i18n import tr
from ..core.tracker import TrackerState
from .settings_dialog import SettingsDialog
from .stats_dialog import StatsDialog

_PROJECT_LABEL_MAX_WIDTH = 100
_WIDGET_MAX_WIDTH = 500  # 0 means no global width limit


# ── Qt5 / Qt6 enum compat ──────────────────────────────────────────────────────


def _qt(root, *chain, fallback=None):
    obj = root
    for attr in chain:
        obj = getattr(obj, attr, None)
        if obj is None:
            return fallback
    return obj if obj is not None else fallback


def _align_center():
    return _qt(Qt, "AlignmentFlag", "AlignCenter") or _qt(Qt, "AlignCenter")


def _elide_right():
    return _qt(Qt, "TextElideMode", "ElideRight") or _qt(Qt, "ElideRight")


def _ctx_menu_policy():
    return _qt(Qt, "ContextMenuPolicy", "CustomContextMenu") or _qt(
        Qt, "CustomContextMenu"
    )


def _pointing_hand():
    return _qt(Qt, "CursorShape", "PointingHandCursor") or _qt(Qt, "PointingHandCursor")


def _app_shortcut():
    return _qt(Qt, "ShortcutContext", "ApplicationShortcut") or _qt(
        Qt, "ApplicationShortcut"
    )


# ── helpers ────────────────────────────────────────────────────────────────────


def _fmt(secs: int) -> str:
    h, rem = divmod(int(secs), 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _monospace_font(size: int) -> QFont:
    preferred = ["Consolas", "Courier New", "DejaVu Sans Mono", "Monospace"]
    try:
        available = QFontDatabase().families()
    except TypeError:
        # PyQt6 may require no-arg call differently
        available = QFontDatabase.families()
    for name in preferred:
        if name in available:
            return QFont(name, size)
    try:
        f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    except AttributeError:
        f = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    f.setPointSize(size)
    return f


# ── per-state visual definitions ───────────────────────────────────────────────

_STATE_STYLE = {
    TrackerState.STOPPED: (
        "QLabel{"
        "color:#4a4a4a;"
        "background:#f0f0f0;"
        "border:1px solid #d0d0d0;"
        "border-radius:6px;"
        "padding:3px 10px;"
        "font-weight:600;"
        "}"
    ),
    TrackerState.RUNNING: (
        "QLabel{"
        "color:#0a3d22;"
        "background:#c8f2db;"
        "border:1px solid #7dcfa5;"
        "border-radius:6px;"
        "padding:3px 10px;"
        "font-weight:700;"
        "}"
    ),
    TrackerState.PAUSED: (
        "QLabel{"
        "color:#5a3c00;"
        "background:#fff0c2;"
        "border:1px solid #f0c840;"
        "border-radius:6px;"
        "padding:3px 10px;"
        "font-weight:700;"
        "}"
    ),
}

_PROJ_STYLE = {
    TrackerState.STOPPED: "QLabel{color:#888;font-size:11px;padding:1px 4px;}",
    TrackerState.RUNNING: "QLabel{color:#0a3d22;font-size:11px;font-weight:600;padding:1px 4px;}",
    TrackerState.PAUSED: "QLabel{color:#5a3c00;font-size:11px;font-weight:600;padding:1px 4px;}",
}

_STATUS_STYLE = {
    TrackerState.STOPPED: "QLabel{color:#666;font-weight:600;padding:2px 4px;}",
    TrackerState.RUNNING: "QLabel{color:#0a6b38;font-weight:700;padding:2px 4px;}",
    TrackerState.PAUSED: "QLabel{color:#8a5b00;font-weight:700;padding:2px 4px;}",
}

_TOGGLE_STYLE = {
    TrackerState.STOPPED: (
        "QPushButton{background:#27ae60;color:#fff;border:none;border-radius:5px;"
        "font-size:15px;font-weight:bold;padding:0px;}"
        "QPushButton:hover{background:#1e8449;}"
        "QPushButton:pressed{background:#145a32;padding-top:1px;}"
        "QPushButton:focus{outline:none;border:none;}"
    ),
    TrackerState.RUNNING: (
        "QPushButton{background:#e67e22;color:#fff;border:none;border-radius:5px;"
        "font-size:15px;font-weight:bold;padding:0px;}"
        "QPushButton:hover{background:#ca6f1e;}"
        "QPushButton:pressed{background:#a04000;padding-top:1px;}"
        "QPushButton:focus{outline:none;border:none;}"
    ),
    TrackerState.PAUSED: (
        "QPushButton{background:#27ae60;color:#fff;border:none;border-radius:5px;"
        "font-size:15px;font-weight:bold;padding:0px;}"
        "QPushButton:hover{background:#1e8449;}"
        "QPushButton:pressed{background:#145a32;padding-top:1px;}"
        "QPushButton:focus{outline:none;border:none;}"
    ),
}

_TOGGLE_ICON = {
    TrackerState.STOPPED: "SP_MediaPlay",
    TrackerState.RUNNING: "SP_MediaPause",
    TrackerState.PAUSED: "SP_MediaPlay",
}

_BTN_UTIL = (
    "QPushButton{{background:{bg};color:#fff;border:none;"
    "border-radius:5px;font-size:13px;padding:0px;}}"
    "QPushButton:hover{{background:{hv};}}"
    "QPushButton:pressed{{background:{hv};padding-top:1px;}}"
    "QPushButton:focus{{outline:none;border:none;}}"
    "QPushButton:disabled{{background:#d8d8d8;color:#aaa;}}"
)

_STOP_STYLE = (
    "QPushButton{background:#c0392b;color:#fff;border:none;"
    "border-radius:5px;font-size:15px;padding:0px;}"
    "QPushButton:hover{background:#a93226;}"
    "QPushButton:pressed{background:#7b241c;padding-top:1px;}"
    "QPushButton:focus{outline:none;border:none;}"
    "QPushButton:disabled{background:#d8d8d8;color:#aaa;}"
)

# Progress bar styles
_PBAR_BASE = (
    "QProgressBar{{"
    "border:1px solid {border};"
    "border-radius:3px;"
    "background:{bg};"
    "height:5px;"
    "text-align:center;"
    "}}"
    "QProgressBar::chunk{{"
    "background:{chunk};"
    "border-radius:2px;"
    "}}"
)

_PBAR_RUNNING = _PBAR_BASE.format(border="#7dcfa5", bg="#e8faf0", chunk="#27ae60")
_PBAR_DONE = _PBAR_BASE.format(border="#2e86c1", bg="#d6eaf8", chunk="#2980b9")
_PBAR_STOPPED = _PBAR_BASE.format(border="#c0c0c0", bg="#f0f0f0", chunk="#aaa")


# ── widget ─────────────────────────────────────────────────────────────────────


class TrackerWidget(QWidget):

    def __init__(self, tracker, persistence, settings, parent=None):
        super().__init__(parent)
        self._tracker = tracker
        self._db = persistence
        self._cfg = settings
        self._build_ui()
        self._wire()
        self._on_project_changed(self._tracker.project_name)
        self._refresh_visibility()

    # ── build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        if _WIDGET_MAX_WIDTH > 0:
            self.setMaximumWidth(_WIDGET_MAX_WIDTH)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 2, 4, 2)
        outer.setSpacing(2)

        # ── top row ───────────────────────────────────────────────────────────
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(4)

        self._status_lbl = QLabel(self._t("Stopped"))
        self._status_lbl.setMinimumWidth(64)
        self._status_lbl.setAccessibleName(self._t("Time Tracker status"))
        self._status_lbl.setStyleSheet(_STATUS_STYLE[TrackerState.STOPPED])
        top.addWidget(self._status_lbl)

        # Project name
        self._proj_lbl = QLabel(self._t("Unsaved project"))
        self._proj_lbl.setMaximumWidth(_PROJECT_LABEL_MAX_WIDTH)
        self._proj_lbl.setStyleSheet(_PROJ_STYLE[TrackerState.STOPPED])
        top.addWidget(self._proj_lbl)

        # Digital clock — right-click for context menu
        self._lbl = QLabel("00:00:00")
        self._lbl.setFont(_monospace_font(17))
        self._lbl.setMinimumWidth(96)
        self._lbl.setAlignment(_align_center())
        self._lbl.setStyleSheet(_STATE_STYLE[TrackerState.STOPPED])
        self._lbl.setContextMenuPolicy(_ctx_menu_policy())
        self._lbl.customContextMenuRequested.connect(self._show_time_menu)
        top.addWidget(self._lbl)

        # Toggle ▶/⏸
        self._btn_toggle = QPushButton()
        self._btn_toggle.setAccessibleName(self._t("Start or pause time tracking"))
        self._btn_toggle.setToolTip(self._toggle_tip(TrackerState.STOPPED))
        self._btn_toggle.setFixedSize(28, 28)
        self._btn_toggle.setStyleSheet(_TOGGLE_STYLE[TrackerState.STOPPED])
        self._btn_toggle.setCursor(_pointing_hand())
        top.addWidget(self._btn_toggle)

        # Stop ⏹
        self._btn_stop = QPushButton()
        self._btn_stop.setAccessibleName(self._t("End the time session"))
        self._set_standard_icon(self._btn_stop, "SP_MediaStop")
        self._btn_stop.setToolTip(self._t("End session"))
        self._btn_stop.setFixedSize(28, 28)
        self._btn_stop.setStyleSheet(_STOP_STYLE)
        self._btn_stop.setCursor(_pointing_hand())
        top.addWidget(self._btn_stop)

        # Stats 📊
        self._btn_stats = QPushButton()
        self._btn_stats.setAccessibleName(self._t("Open Time Tracker statistics"))
        self._set_standard_icon(self._btn_stats, "SP_FileDialogDetailedView")
        self._btn_stats.setToolTip(self._t("Statistics and history"))
        self._btn_stats.setFixedSize(28, 28)
        self._btn_stats.setStyleSheet(_BTN_UTIL.format(bg="#2980b9", hv="#1f618d"))
        self._btn_stats.setCursor(_pointing_hand())
        top.addWidget(self._btn_stats)

        # Settings ⚙
        self._btn_cfg = QPushButton()
        self._btn_cfg.setAccessibleName(self._t("Open Time Tracker settings"))
        self._set_standard_icon(self._btn_cfg, "SP_FileDialogContentsView")
        self._btn_cfg.setToolTip(self._t("Settings"))
        self._btn_cfg.setFixedSize(28, 28)
        self._btn_cfg.setStyleSheet(_BTN_UTIL.format(bg="#717d7e", hv="#566573"))
        self._btn_cfg.setCursor(_pointing_hand())
        top.addWidget(self._btn_cfg)

        outer.addLayout(top)

        # ── daily progress bar (optional) ─────────────────────────────────────
        self._pbar = QProgressBar()
        self._pbar.setRange(0, 100)
        self._pbar.setValue(0)
        self._pbar.setTextVisible(False)
        self._pbar.setFixedHeight(5)
        self._pbar.setStyleSheet(_PBAR_STOPPED)
        self._pbar.setToolTip(self._t("Daily progress: 0%"))
        self._pbar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        outer.addWidget(self._pbar)

        self._apply_state(TrackerState.STOPPED)

        # Keyboard shortcut Ctrl+Alt+T
        self._shortcut = QShortcut(QKeySequence("Ctrl+Alt+T"), self)
        self._shortcut.setContext(_app_shortcut())
        self._shortcut.activated.connect(self._tracker.toggle)

    def _set_standard_icon(self, button, name):
        enum_owner = getattr(QStyle, "StandardPixmap", QStyle)
        standard_pixmap = getattr(enum_owner, name, None)
        if standard_pixmap is None:
            standard_pixmap = getattr(QStyle, name, None)
        if standard_pixmap is not None:
            button.setIcon(self.style().standardIcon(standard_pixmap))

    # ── wire signals ──────────────────────────────────────────────────────────

    def _wire(self):
        self._btn_toggle.clicked.connect(self._tracker.toggle)
        self._btn_stop.clicked.connect(self._tracker.stop)
        self._btn_stats.clicked.connect(self._open_stats)
        self._btn_cfg.clicked.connect(self._open_settings)

        self._tracker.time_updated.connect(self._on_time)
        self._tracker.state_changed.connect(self._on_state)
        self._tracker.project_changed.connect(self._on_project_changed)
        self._tracker.settings_changed.connect(self._refresh_visibility)

        if hasattr(self._tracker, "session_completed"):
            self._tracker.session_completed.connect(self._on_session_completed)

        if hasattr(self._tracker, "daily_updated"):
            self._tracker.daily_updated.connect(self._on_daily_updated)

    # ── slots ─────────────────────────────────────────────────────────────────

    def _on_time(self, secs: int):
        self._lbl.setText(_fmt(secs))
        self._update_lbl_tooltip(secs)
        if self._cfg.show_daily_progress and self._cfg.daily_goal_hours > 0:
            self._on_daily_updated(self._tracker.today_seconds())

    def _update_lbl_tooltip(self, secs: int):
        state = self._tracker.state
        labels = {
            TrackerState.STOPPED: self._t("Stopped"),
            TrackerState.RUNNING: self._t("Tracking"),
            TrackerState.PAUSED: self._t("Paused"),
        }
        self._lbl.setToolTip(
            self._t(
                "State: {state}\nProject total: {total}\n"
                "Right-click to copy · Ctrl+Alt+T to toggle",
                state=labels.get(state, "—"),
                total=_fmt(secs),
            )
        )

    def _on_state(self, state_name: str):
        state = TrackerState(state_name)
        self._apply_state(state)

    def _on_project_changed(self, name: str):
        if not name:
            self._proj_lbl.setText(self._t("Unsaved project"))
            self._proj_lbl.setToolTip("")
            return
        if name in {"Unsaved project", "Projeto não salvo"}:
            name = self._t("Unsaved project")
        fm = QFontMetrics(self._proj_lbl.font())
        elided = fm.elidedText(name, _elide_right(), _PROJECT_LABEL_MAX_WIDTH - 8)
        self._proj_lbl.setText(elided)
        key = self._tracker.project_key or ""
        self._proj_lbl.setToolTip(
            f"{name}\n{key}" if key and not key.startswith("__unsaved__") else name
        )

    def _on_session_completed(self, elapsed: int):
        if not self._cfg.notify_on_session_end or elapsed <= 0:
            return
        try:
            iface.messageBar().pushInfo(
                self._t("Time Tracker"),
                self._t("Session ended – duration: {duration}", duration=_fmt(elapsed)),
            )
        except (AttributeError, RuntimeError):
            # A barra de mensagens pode já ter sido destruída no encerramento.
            return

    def _on_daily_updated(self, today_secs: int):
        """Update progress bar with today's total seconds."""
        goal_secs = self._cfg.daily_goal_hours * 3600
        if goal_secs <= 0 or not self._cfg.show_daily_progress:
            return
        pct = min(100, int(today_secs * 100 / goal_secs))
        self._pbar.setValue(pct)
        remaining = max(0, goal_secs - today_secs)
        tip = (
            self._t(
                "Today: {today} / {goal}\nProgress: {percent}%",
                today=_fmt(today_secs),
                goal=_fmt(goal_secs),
                percent=pct,
            )
        )
        if remaining > 0:
            tip += "\n" + self._t("Remaining: {remaining}", remaining=_fmt(remaining))
        else:
            tip += "\n✓ " + self._t("Daily goal reached!")
        self._pbar.setToolTip(tip)
        # Colour: blue when goal met, green otherwise
        state = self._tracker.state
        if pct >= 100:
            self._pbar.setStyleSheet(_PBAR_DONE)
        elif state == TrackerState.RUNNING:
            self._pbar.setStyleSheet(_PBAR_RUNNING)
        else:
            self._pbar.setStyleSheet(_PBAR_STOPPED)

    def _refresh_visibility(self):
        self._retranslate()
        self._proj_lbl.setVisible(self._cfg.show_project_name)
        show_pbar = self._cfg.show_daily_progress and self._cfg.daily_goal_hours > 0
        self._pbar.setVisible(show_pbar)
        if show_pbar:
            # Force an immediate update
            today = self._tracker.today_seconds()
            self._on_daily_updated(today)

    def _apply_state(self, state: TrackerState):
        self._lbl.setStyleSheet(_STATE_STYLE[state])
        self._proj_lbl.setStyleSheet(_PROJ_STYLE[state])
        self._status_lbl.setStyleSheet(_STATUS_STYLE[state])

        status_text = {
            TrackerState.STOPPED: self._t("Stopped"),
            TrackerState.RUNNING: self._t("Tracking"),
            TrackerState.PAUSED: self._t("Paused"),
        }[state]
        if state == TrackerState.PAUSED:
            reason = {
                "idle": self._t("inactivity"),
                "focus": self._t("QGIS out of focus"),
                "manual": self._t("manual"),
            }.get(self._tracker.pause_reason)
            if reason:
                status_text = self._t("Pause: {reason}", reason=reason)
        self._status_lbl.setText(status_text)
        self._status_lbl.setToolTip(
            self._t("Current state: {state}", state=status_text)
        )

        self._set_standard_icon(self._btn_toggle, _TOGGLE_ICON[state])
        self._btn_toggle.setStyleSheet(_TOGGLE_STYLE[state])
        self._btn_toggle.setToolTip(self._toggle_tip(state))

        self._btn_stop.setEnabled(state != TrackerState.STOPPED)

        self._update_lbl_tooltip(self._tracker.current_seconds())

        # Refresh progress bar style on state change
        if self._cfg.show_daily_progress and self._cfg.daily_goal_hours > 0:
            pct = self._pbar.value()
            if pct >= 100:
                self._pbar.setStyleSheet(_PBAR_DONE)
            elif state == TrackerState.RUNNING:
                self._pbar.setStyleSheet(_PBAR_RUNNING)
            else:
                self._pbar.setStyleSheet(_PBAR_STOPPED)

    # ── context menu on timer label ───────────────────────────────────────────

    def _show_time_menu(self, pos: QPoint):
        menu = QMenu(self)
        a_copy = menu.addAction(self._t("Copy time"))
        a_copy.triggered.connect(self._copy_time)
        menu.addSeparator()
        a_toggle = menu.addAction(
            self._t("Pause")
            if self._tracker.state == TrackerState.RUNNING
            else self._t("Start")
        )
        a_toggle.triggered.connect(self._tracker.toggle)
        a_stop = menu.addAction(self._t("End"))
        a_stop.setEnabled(self._tracker.state != TrackerState.STOPPED)
        a_stop.triggered.connect(self._tracker.stop)
        menu.exec(self._lbl.mapToGlobal(pos))

    def _copy_time(self):
        QApplication.clipboard().setText(self._lbl.text())

    # ── dialogs ───────────────────────────────────────────────────────────────

    def _open_stats(self):
        dlg = StatsDialog(
            self._db, tracker=self._tracker, settings=self._cfg, parent=self
        )
        dlg.exec()

    def _open_settings(self):
        dlg = SettingsDialog(self._cfg, self._tracker, parent=self)
        dlg.exec()

    def _t(self, text, **values):
        return tr(text, getattr(self._cfg, "language", "en"), **values)

    def _toggle_tip(self, state):
        source = {
            TrackerState.STOPPED: "Start  (Ctrl+Alt+T)",
            TrackerState.RUNNING: "Pause  (Ctrl+Alt+T)",
            TrackerState.PAUSED: "Resume  (Ctrl+Alt+T)",
        }[state]
        return self._t(source)

    def _retranslate(self):
        """Refresh toolbar text immediately after the language setting changes."""
        self._status_lbl.setAccessibleName(self._t("Time Tracker status"))
        self._btn_toggle.setAccessibleName(self._t("Start or pause time tracking"))
        self._btn_stop.setAccessibleName(self._t("End the time session"))
        self._btn_stop.setToolTip(self._t("End session"))
        self._btn_stats.setAccessibleName(self._t("Open Time Tracker statistics"))
        self._btn_stats.setToolTip(self._t("Statistics and history"))
        self._btn_cfg.setAccessibleName(self._t("Open Time Tracker settings"))
        self._btn_cfg.setToolTip(self._t("Settings"))
        self._apply_state(self._tracker.state)
        self._on_project_changed(self._tracker.project_name)
