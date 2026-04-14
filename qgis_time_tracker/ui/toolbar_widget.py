"""
TrackerWidget – compact toolbar strip:
  [nome_projeto] [00:00:00] [▶] [⏸] [⏹] [📊] [⚙]

Timer label colour changes with state:
  STOPPED  → grey
  RUNNING  → green
  PAUSED   → amber

Project label is elided at 170 px and shows the full name in a tooltip.
Font for the timer falls back gracefully when Consolas is not available.
"""

from qgis.PyQt.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QFont, QFontDatabase, QFontMetrics

from ..core.tracker import TrackerState
from .settings_dialog import SettingsDialog
from .stats_dialog import StatsDialog


_PROJECT_LABEL_MAX_WIDTH = 170  # px – elide beyond this

def _fmt(secs: int) -> str:
    h, rem = divmod(int(secs), 3600)
    m, s   = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _monospace_font(size: int) -> QFont:
    """Return the best available fixed-width font at the given point size."""
    preferred = ["Consolas", "Courier New", "DejaVu Sans Mono", "Monospace"]
    available = QFontDatabase().families()
    for name in preferred:
        if name in available:
            return QFont(name, size)
    # Ultimate fallback – Qt built-in fixed font
    f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    f.setPointSize(size)
    return f


# ── per-state styles ───────────────────────────────────────────────────────────

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

_PROJ_LABEL_STYLE = {
    TrackerState.STOPPED: "QLabel{color:#777;font-size:11px;padding:2px 4px;}",
    TrackerState.RUNNING: "QLabel{color:#0f5132;font-size:11px;font-weight:600;padding:2px 4px;}",
    TrackerState.PAUSED:  "QLabel{color:#664d03;font-size:11px;font-weight:600;padding:2px 4px;}",
}

# action buttons (play / pause / stop) – larger icon
_BTN_ACTION = (
    "QPushButton{{background:{bg};color:#fff;border:none;"
    "border-radius:4px;font-size:16px;padding:0px;}}"
    "QPushButton:hover{{background:{hv};}}"
    "QPushButton:pressed{{background:{hv};padding-top:1px;}}"
    "QPushButton:focus{{outline:none;border:none;}}"
    "QPushButton:disabled{{background:#d0d0d0;color:#a0a0a0;}}"
)

# utility buttons (stats / cfg) – smaller icon, neutral tone
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
        self._tracker  = tracker
        self._db       = persistence
        self._cfg      = settings
        self._build_ui()
        self._wire()
        # Initialise project label with whatever is already loaded
        self._on_project_changed(self._tracker.project_name)

    # ── build ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.setSpacing(4)

        # Project name label
        self._proj_lbl = QLabel("Nenhum projeto")
        self._proj_lbl.setMaximumWidth(_PROJECT_LABEL_MAX_WIDTH)
        self._proj_lbl.setStyleSheet(_PROJ_LABEL_STYLE[TrackerState.STOPPED])
        lay.addWidget(self._proj_lbl)

        # Digital clock label
        self._lbl = QLabel("00:00:00")
        self._lbl.setFont(_monospace_font(18))
        self._lbl.setMinimumWidth(100)
        self._lbl.setAlignment(Qt.AlignCenter)
        self._lbl.setStyleSheet(_STATE_STYLE[TrackerState.STOPPED])
        lay.addWidget(self._lbl)

        self._btn_play  = self._mk_btn("▶",  "Iniciar / Retomar", "#27ae60", "#1e8449", action=True)
        self._btn_pause = self._mk_btn("⏸",  "Pausar",            "#e67e22", "#ca6f1e", action=True)
        self._btn_stop  = self._mk_btn("⏹",  "Parar",             "#e74c3c", "#cb4335", action=True)
        self._btn_stats = self._mk_btn("📊", "Estatísticas",       "#2980b9", "#1a5276", action=False)
        self._btn_cfg   = self._mk_btn("⚙",  "Configurações",      "#7f8c8d", "#626567", action=False)

        for btn in (
            self._btn_play, self._btn_pause, self._btn_stop,
            self._btn_stats, self._btn_cfg,
        ):
            lay.addWidget(btn)

        self._apply_state(TrackerState.STOPPED)

    def _mk_btn(
        self, label: str, tip: str, bg: str, hv: str, action: bool = True
    ) -> QPushButton:
        btn = QPushButton(label)
        btn.setToolTip(tip)
        btn.setFixedSize(28, 28)
        template = _BTN_ACTION if action else _BTN_UTIL
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
        self._tracker.project_changed.connect(self._on_project_changed)

    # ── slots ─────────────────────────────────────────────────────────────────

    def _on_time(self, secs: int):
        self._lbl.setText(_fmt(secs))

    def _on_state(self, state_name: str):
        state = TrackerState(state_name)
        self._apply_state(state)

    def _on_project_changed(self, name: str):
        """Update the project label with elision and tooltip."""
        if not name:
            self._proj_lbl.setText("Nenhum projeto")
            self._proj_lbl.setToolTip("")
            return

        fm     = QFontMetrics(self._proj_lbl.font())
        elided = fm.elidedText(name, Qt.ElideRight, _PROJECT_LABEL_MAX_WIDTH - 8)
        self._proj_lbl.setText(elided)
        # Show full name + path hint in tooltip
        key = self._tracker.project_key or ""
        self._proj_lbl.setToolTip(
            f"{name}\n{key}" if key and key != "__unsaved__" else name
        )

    def _apply_state(self, state: TrackerState):
        self._lbl.setStyleSheet(_STATE_STYLE[state])
        self._proj_lbl.setStyleSheet(_PROJ_LABEL_STYLE[state])
        self._btn_play.setEnabled(state != TrackerState.RUNNING)
        self._btn_pause.setEnabled(state == TrackerState.RUNNING)
        self._btn_stop.setEnabled(state != TrackerState.STOPPED)

    # ── dialogs ───────────────────────────────────────────────────────────────

    def _open_stats(self):
        dlg = StatsDialog(self._db, tracker=self._tracker, parent=self)
        dlg.exec_()

    def _open_settings(self):
        dlg = SettingsDialog(self._cfg, self._tracker, parent=self)
        dlg.exec_()