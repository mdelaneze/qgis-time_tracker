"""
TrackerWidget – compact toolbar strip:
  [nome_projeto] [00:00:00] [▶/⏸] [⏹] [📊] [⚙]

Timer label colour changes with state:
  STOPPED  → grey
  RUNNING  → green
  PAUSED   → amber

Project label is elided at 170 px and shows the full name in a tooltip.
Font for the timer falls back gracefully when Consolas is not available.

Keyboard shortcut
-----------------
  Ctrl+Alt+T  – toggle (start/pause)  — ApplicationShortcut, works
                even when the toolbar widget does not have focus.
"""

from qgis.PyQt.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QApplication, QMenu,
)
from qgis.PyQt.QtCore import Qt, QPoint
from qgis.PyQt.QtGui import QFont, QFontDatabase, QFontMetrics
from qgis.PyQt.QtWidgets import QShortcut
from qgis.PyQt.QtGui import QKeySequence
from qgis.utils import iface

from ..core.tracker import TrackerState
from .settings_dialog import SettingsDialog
from .stats_dialog import StatsDialog


_PROJECT_LABEL_MAX_WIDTH = 170


def _fmt(secs: int) -> str:
    h, rem = divmod(int(secs), 3600)
    m, s   = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _monospace_font(size: int) -> QFont:
    preferred = ["Consolas", "Courier New", "DejaVu Sans Mono", "Monospace"]
    available = QFontDatabase().families()
    for name in preferred:
        if name in available:
            return QFont(name, size)
    f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    f.setPointSize(size)
    return f


# ── per-state styles ───────────────────────────────────────────────────────────

_STATE_STYLE = {
    TrackerState.STOPPED: (
        "QLabel{color:#2b2b2b;background:#f5f5f5;border:1px solid #e0e0e0;"
        "border-radius:6px;padding:4px 10px;font-weight:600;}"
    ),
    TrackerState.RUNNING: (
        "QLabel{color:#0f5132;background:#d1f2eb;border:1px solid #a3e4d7;"
        "border-radius:6px;padding:4px 10px;font-weight:700;}"
    ),
    TrackerState.PAUSED: (
        "QLabel{color:#664d03;background:#fff3cd;border:1px solid #ffecb5;"
        "border-radius:6px;padding:4px 10px;font-weight:700;}"
    ),
}

_PROJ_LABEL_STYLE = {
    TrackerState.STOPPED: "QLabel{color:#777;font-size:11px;padding:2px 4px;}",
    TrackerState.RUNNING: "QLabel{color:#0f5132;font-size:11px;font-weight:600;padding:2px 4px;}",
    TrackerState.PAUSED:  "QLabel{color:#664d03;font-size:11px;font-weight:600;padding:2px 4px;}",
}

# Toggle button muda cor conforme estado
_TOGGLE_STYLE = {
    TrackerState.STOPPED: (   # verde – convida a iniciar
        "QPushButton{background:#27ae60;color:#fff;border:none;border-radius:4px;"
        "font-size:16px;padding:0px;}"
        "QPushButton:hover{background:#1e8449;}"
        "QPushButton:pressed{background:#1e8449;padding-top:1px;}"
        "QPushButton:focus{outline:none;border:none;}"
    ),
    TrackerState.RUNNING: (   # âmbar – indica que pausar é a ação disponível
        "QPushButton{background:#e67e22;color:#fff;border:none;border-radius:4px;"
        "font-size:16px;padding:0px;}"
        "QPushButton:hover{background:#ca6f1e;}"
        "QPushButton:pressed{background:#ca6f1e;padding-top:1px;}"
        "QPushButton:focus{outline:none;border:none;}"
    ),
    TrackerState.PAUSED: (    # verde – convida a retomar
        "QPushButton{background:#27ae60;color:#fff;border:none;border-radius:4px;"
        "font-size:16px;padding:0px;}"
        "QPushButton:hover{background:#1e8449;}"
        "QPushButton:pressed{background:#1e8449;padding-top:1px;}"
        "QPushButton:focus{outline:none;border:none;}"
    ),
}

_TOGGLE_ICON = {
    TrackerState.STOPPED: "▶",
    TrackerState.RUNNING: "⏸",
    TrackerState.PAUSED:  "▶",
}

_TOGGLE_TIP = {
    TrackerState.STOPPED: "Start  (Ctrl+Alt+T)",
    TrackerState.RUNNING: "Pause  (Ctrl+Alt+T)",
    TrackerState.PAUSED:  "Resume  (Ctrl+Alt+T)",
}

_BTN_UTIL = (
    "QPushButton{{background:{bg};color:#fff;border:none;"
    "border-radius:4px;font-size:13px;padding:0px;}}"
    "QPushButton:hover{{background:{hv};}}"
    "QPushButton:pressed{{background:{hv};padding-top:1px;}}"
    "QPushButton:focus{{outline:none;border:none;}}"
    "QPushButton:disabled{{background:#d0d0d0;color:#a0a0a0;}}"
)


class TrackerWidget(QWidget):

    def __init__(self, tracker, persistence, settings, parent=None):
        super().__init__(parent)
        self._tracker = tracker
        self._db      = persistence
        self._cfg     = settings
        self._build_ui()
        self._wire()
        self._on_project_changed(self._tracker.project_name)
        self._refresh_project_label_visibility()

    # ── build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(4)

        # Project name label
        self._proj_lbl = QLabel("Unsaved project")
        self._proj_lbl.setMaximumWidth(_PROJECT_LABEL_MAX_WIDTH)
        self._proj_lbl.setStyleSheet(_PROJ_LABEL_STYLE[TrackerState.STOPPED])
        lay.addWidget(self._proj_lbl)

        # Digital clock label — context menu on right-click
        self._lbl = QLabel("00:00:00")
        self._lbl.setFont(_monospace_font(18))
        self._lbl.setMinimumWidth(100)
        self._lbl.setAlignment(Qt.AlignCenter)
        self._lbl.setStyleSheet(_STATE_STYLE[TrackerState.STOPPED])
        self._lbl.setContextMenuPolicy(Qt.CustomContextMenu)
        self._lbl.customContextMenuRequested.connect(self._show_time_context_menu)
        lay.addWidget(self._lbl)

        # ── Toggle (▶/⏸) – único botão play+pause ──────────────────────────
        self._btn_toggle = QPushButton("▶")
        self._btn_toggle.setToolTip(_TOGGLE_TIP[TrackerState.STOPPED])
        self._btn_toggle.setFixedSize(28, 28)
        self._btn_toggle.setStyleSheet(_TOGGLE_STYLE[TrackerState.STOPPED])
        self._btn_toggle.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self._btn_toggle)

        # Stop
        self._btn_stop = QPushButton("⏹")
        self._btn_stop.setToolTip("Stop")
        self._btn_stop.setFixedSize(28, 28)
        self._btn_stop.setStyleSheet(
            "QPushButton{background:#e74c3c;color:#fff;border:none;"
            "border-radius:4px;font-size:16px;padding:0px;}"
            "QPushButton:hover{background:#cb4335;}"
            "QPushButton:pressed{background:#cb4335;padding-top:1px;}"
            "QPushButton:focus{outline:none;border:none;}"
            "QPushButton:disabled{background:#d0d0d0;color:#a0a0a0;}"
        )
        self._btn_stop.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self._btn_stop)

        # Stats
        self._btn_stats = QPushButton("📊")
        self._btn_stats.setToolTip("Stats")
        self._btn_stats.setFixedSize(28, 28)
        self._btn_stats.setStyleSheet(
            _BTN_UTIL.format(bg="#2980b9", hv="#1a5276")
        )
        self._btn_stats.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self._btn_stats)

        # Settings
        self._btn_cfg = QPushButton("⚙")
        self._btn_cfg.setToolTip("Settings")
        self._btn_cfg.setFixedSize(28, 28)
        self._btn_cfg.setStyleSheet(
            _BTN_UTIL.format(bg="#7f8c8d", hv="#626567")
        )
        self._btn_cfg.setCursor(Qt.PointingHandCursor)
        lay.addWidget(self._btn_cfg)

        self._apply_state(TrackerState.STOPPED)

        # Atalho global Ctrl+Alt+T
        self._shortcut = QShortcut(QKeySequence("Ctrl+Alt+T"), self)
        self._shortcut.setContext(Qt.ApplicationShortcut)
        self._shortcut.activated.connect(self._tracker.toggle)

    # ── wire signals ──────────────────────────────────────────────────────────

    def _wire(self):
        self._btn_toggle.clicked.connect(self._tracker.toggle)
        self._btn_stop.clicked.connect(self._tracker.stop)
        self._btn_stats.clicked.connect(self._open_stats)
        self._btn_cfg.clicked.connect(self._open_settings)

        self._tracker.time_updated.connect(self._on_time)
        self._tracker.state_changed.connect(self._on_state)
        self._tracker.project_changed.connect(self._on_project_changed)
        self._tracker.settings_changed.connect(self._refresh_project_label_visibility)

        if hasattr(self._tracker, "session_completed"):
            self._tracker.session_completed.connect(self._on_session_completed)

    # ── slots ─────────────────────────────────────────────────────────────────

    def _on_time(self, secs: int):
        self._lbl.setText(_fmt(secs))
        self._update_lbl_tooltip(secs)

    def _update_lbl_tooltip(self, secs: int):
        state = self._tracker.state
        state_labels = {
            TrackerState.STOPPED: "Stopped",
            TrackerState.RUNNING: "Running",
            TrackerState.PAUSED:  "Paused",
        }
        self._lbl.setToolTip(
            f"State: {state_labels.get(state, '—')}\n"
            f"Total: {_fmt(secs)}\n"
            f"Right-click to copy  |  Ctrl+Alt+T to toggle"
        )

    def _on_state(self, state_name: str):
        state = TrackerState(state_name)
        self._apply_state(state)

    def _on_project_changed(self, name: str):
        if not name:
            self._proj_lbl.setText("Unsaved project")
            self._proj_lbl.setToolTip("")
            return
        fm     = QFontMetrics(self._proj_lbl.font())
        elided = fm.elidedText(name, Qt.ElideRight, _PROJECT_LABEL_MAX_WIDTH - 8)
        self._proj_lbl.setText(elided)
        key = self._tracker.project_key or ""
        self._proj_lbl.setToolTip(
            f"{name}\n{key}" if key and key != "__unsaved__" else name
        )

    def _on_session_completed(self, elapsed: int):
        if not self._cfg.notify_on_session_end or elapsed <= 0:
            return
        try:
            iface.messageBar().pushInfo(
                "Time Tracker",
                f"Session ended – duration: {_fmt(elapsed)}",
            )
        except Exception:
            pass

    def _refresh_project_label_visibility(self):
        self._proj_lbl.setVisible(self._cfg.show_project_name)

    def _apply_state(self, state: TrackerState):
        # Timer label
        self._lbl.setStyleSheet(_STATE_STYLE[state])
        self._proj_lbl.setStyleSheet(_PROJ_LABEL_STYLE[state])

        # Toggle button: ícone + cor + tooltip mudam com estado
        self._btn_toggle.setText(_TOGGLE_ICON[state])
        self._btn_toggle.setStyleSheet(_TOGGLE_STYLE[state])
        self._btn_toggle.setToolTip(_TOGGLE_TIP[state])

        # Stop só habilita quando há algo rodando ou pausado
        self._btn_stop.setEnabled(state != TrackerState.STOPPED)

        # Atualiza tooltip do timer
        self._update_lbl_tooltip(self._tracker.current_seconds())

    # ── context menu no label de tempo ────────────────────────────────────────

    def _show_time_context_menu(self, pos: QPoint):
        menu = QMenu(self)
        action = menu.addAction("📋  Copy time")
        action.triggered.connect(self._copy_time)
        menu.exec_(self._lbl.mapToGlobal(pos))

    def _copy_time(self):
        QApplication.clipboard().setText(self._lbl.text())

    # ── dialogs ───────────────────────────────────────────────────────────────

    def _open_stats(self):
        dlg = StatsDialog(self._db, tracker=self._tracker, parent=self)
        dlg.exec_()

    def _open_settings(self):
        dlg = SettingsDialog(self._cfg, self._tracker, parent=self)
        dlg.exec_()
