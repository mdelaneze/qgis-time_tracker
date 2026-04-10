"""
TrackerWidget – compact toolbar strip:
  [00:00:00] [▶] [⏸] [⏹] [📊] [⚙]

Timer label colour changes with state:
  STOPPED  → grey
  RUNNING  → green
  PAUSED   → amber
"""

from qgis.PyQt.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont

from ..core.tracker import TrackerState
from .settings_dialog import SettingsDialog
from .stats_dialog import StatsDialog


def _fmt(secs: int) -> str:
    h, rem = divmod(int(secs), 3600)
    m, s   = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


_STATE_STYLE = {
    TrackerState.STOPPED: (
        "QLabel{"
        "color:#2b2b2b;"
        "background:#f5f5f5;"
        "border:1px solid #e0e0e0;"
        "border-radius:6px;"
        "padding:4px 10px;"
        "font-weight:600;"
        "}"
    ),
    TrackerState.RUNNING: (
        "QLabel{"
        "color:#0f5132;"
        "background:#d1f2eb;"
        "border:1px solid #a3e4d7;"
        "border-radius:6px;"
        "padding:4px 10px;"
        "font-weight:700;"
        "}"
    ),
    TrackerState.PAUSED: (
        "QLabel{"
        "color:#664d03;"
        "background:#fff3cd;"
        "border:1px solid #ffecb5;"
        "border-radius:6px;"
        "padding:4px 10px;"
        "font-weight:700;"
        "}"
    ),
}

# botões de ação (play / pause / stop) — ícone maior
_BTN_ACTION_STYLE = (
    "QPushButton{{background:{bg};color:#fff;border:none;"
    "border-radius:4px;font-size:16px;padding:0px;}}"
    "QPushButton:hover{{background:{hv};}}"
    "QPushButton:pressed{{background:{hv};padding-top:1px;}}"
    "QPushButton:focus{{outline:none;border:none;}}"
    "QPushButton:disabled{{background:#d0d0d0;color:#a0a0a0;}}"
)

# botões utilitários (stats / cfg) — ícone menor, tom neutro
_BTN_UTIL_STYLE = (
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
        self._tracker  = tracker
        self._db       = persistence
        self._cfg      = settings
        self._build_ui()
        self._wire()

    # ── build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(4)

        # digital clock label
        self._lbl = QLabel("00:00:00")
        self._lbl.setFont(QFont("Consolas", 18))
        self._lbl.setMinimumWidth(100)
        self._lbl.setAlignment(Qt.AlignCenter)
        self._lbl.setStyleSheet(_STATE_STYLE[TrackerState.STOPPED])
        lay.addWidget(self._lbl)

        self._btn_play  = self._mk_btn("▶",  "Start / Resume", "#27ae60", "#1e8449", action=True)
        self._btn_pause = self._mk_btn("⏸",  "Pause",          "#e67e22", "#ca6f1e", action=True)
        self._btn_stop  = self._mk_btn("⏹",  "Stop",           "#e74c3c", "#cb4335", action=True)
        self._btn_stats = self._mk_btn("📊", "Statistics",      "#2980b9", "#1a5276", action=False)
        self._btn_cfg   = self._mk_btn("⚙",  "Settings",        "#7f8c8d", "#626567", action=False)

        for btn in (
            self._btn_play, self._btn_pause, self._btn_stop,
            self._btn_stats, self._btn_cfg,
        ):
            lay.addWidget(btn)

        self._apply_state(TrackerState.STOPPED)

    def _mk_btn(self, label: str, tip: str, bg: str, hv: str, action: bool = True) -> QPushButton:
        btn = QPushButton(label)
        btn.setToolTip(tip)
        btn.setFixedSize(28, 28)
        template = _BTN_ACTION_STYLE if action else _BTN_UTIL_STYLE
        btn.setStyleSheet(template.format(bg=bg, hv=hv))
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    # ── wire signals ──────────────────────────────────────────────────────────

    def _wire(self):
        self._btn_play.clicked.connect(self._tracker.start)
        self._btn_pause.clicked.connect(self._tracker.pause)
        self._btn_stop.clicked.connect(self._tracker.stop)
        self._btn_stats.clicked.connect(self._open_stats)
        self._btn_cfg.clicked.connect(self._open_settings)

        self._tracker.time_updated.connect(self._on_time)
        self._tracker.state_changed.connect(self._on_state)

    # ── slots ─────────────────────────────────────────────────────────────────

    def _on_time(self, secs: int):
        self._lbl.setText(_fmt(secs))

    def _on_state(self, state_name: str):
        state = TrackerState(state_name)
        self._apply_state(state)

    def _apply_state(self, state: TrackerState):
        self._lbl.setStyleSheet(_STATE_STYLE[state])
        self._btn_play.setEnabled(state != TrackerState.RUNNING)
        self._btn_pause.setEnabled(state == TrackerState.RUNNING)
        self._btn_stop.setEnabled(state != TrackerState.STOPPED)

    # ── dialogs ───────────────────────────────────────────────────────────────

    def _open_stats(self):
        dlg = StatsDialog(self._db, parent=self)
        dlg.exec_()

    def _open_settings(self):
        dlg = SettingsDialog(self._cfg, self._tracker, parent=self)
        dlg.exec_()