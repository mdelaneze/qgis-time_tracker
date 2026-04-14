from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QSpinBox, QCheckBox,
    QDialogButtonBox, QGroupBox, QHBoxLayout, QLabel, QSlider,
)
from qgis.PyQt.QtCore import Qt


class SettingsDialog(QDialog):

    def __init__(self, settings, tracker, parent=None):
        super().__init__(parent)
        self._cfg     = settings
        self._tracker = tracker
        self.setWindowTitle("Time Tracker – Settings")
        self.setMinimumWidth(420)
        self._build_ui()
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(self)

        # ── Auto-Pause ────────────────────────────────────────────────────────
        grp_pause = QGroupBox("Auto-Pause")
        form = QFormLayout(grp_pause)

        self._spin_idle = QSpinBox()
        self._spin_idle.setRange(0, 480)
        self._spin_idle.setSuffix(" min")
        self._spin_idle.setSpecialValueText("No auto-pause")
        self._spin_idle.setToolTip(
            "Auto-pause automatically after this number of minutes without activity.\n"
            "Set to 0 to disable."
        )
        form.addRow("Idle timeout:", self._spin_idle)

        self._chk_focus = QCheckBox(
            "Pause when QGIS loses focus or is minimized"
        )
        form.addRow(self._chk_focus)
        root.addWidget(grp_pause)

        # ── Auto-Start ────────────────────────────────────────────────────────
        grp_start = QGroupBox("Auto-Start")
        form2 = QFormLayout(grp_start)
        self._chk_autostart = QCheckBox(
            "Start tracking automatically when opening a project"
        )
        form2.addRow(self._chk_autostart)
        root.addWidget(grp_start)

        # ── Sessões ───────────────────────────────────────────────────────────
        grp_sess = QGroupBox("Sessões")
        form3 = QFormLayout(grp_sess)

        self._spin_min_session = QSpinBox()
        self._spin_min_session.setRange(0, 300)
        self._spin_min_session.setSuffix(" s")
        self._spin_min_session.setSpecialValueText("No minimum")
        self._spin_min_session.setToolTip(
            "Sessions with duration below this value will be discarded when pausing/ stopping.\n"
            "Useful to ignore accidental clicks on the start button.\n"
            "Set to 0 to record all sessions."
        )
        form3.addRow("Minimum session duration:", self._spin_min_session)

        slider_row = QHBoxLayout()
        self._sld_min_session = QSlider(Qt.Horizontal)
        self._sld_min_session.setRange(0, 300)
        self._sld_min_session.setTickInterval(30)
        self._sld_min_session.setTickPosition(QSlider.TicksBelow)
        self._sld_min_session.setToolTip("Drag to adjust the minimum duration.")
        self._spin_min_session.valueChanged.connect(self._sld_min_session.setValue)
        self._sld_min_session.valueChanged.connect(self._spin_min_session.setValue)
        slider_row.addWidget(QLabel("0 s"))
        slider_row.addWidget(self._sld_min_session, 1)
        slider_row.addWidget(QLabel("5 min"))
        form3.addRow(slider_row)

        self._chk_notify_session = QCheckBox("Notify when session ends")
        self._chk_notify_session.setToolTip(
            "Displays a notification in the QGIS message bar\n"
            "informing about the duration of each session when pausing or stopping."
        )
        form3.addRow(self._chk_notify_session)
        root.addWidget(grp_sess)

        # ── Interface ─────────────────────────────────────────────────────────
        grp_ui = QGroupBox("Interface")
        form4 = QFormLayout(grp_ui)

        self._chk_confirm_reset = QCheckBox(
            "Request confirmation before resetting a project's time"
        )
        self._chk_confirm_reset.setToolTip(
            "When checked, a confirmation dialog will be displayed before\n"
            "any reset operation in the Time Tracker and Statistics window."
        )
        form4.addRow(self._chk_confirm_reset)

        self._chk_project_name = QCheckBox(
            "Display project name in the toolbar"
        )
        self._chk_project_name.setToolTip(
            "Shows a label with the active project name next to the time counter."
        )
        form4.addRow(self._chk_project_name)
        root.addWidget(grp_ui)

        # ── Buttons ───────────────────────────────────────────────────────────
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _load(self):
        self._spin_idle.setValue(self._cfg.idle_timeout_minutes)
        self._chk_focus.setChecked(self._cfg.pause_on_focus_loss)
        self._chk_autostart.setChecked(self._cfg.auto_start_on_open)
        self._spin_min_session.setValue(self._cfg.min_session_seconds)
        self._sld_min_session.setValue(self._cfg.min_session_seconds)
        self._chk_notify_session.setChecked(self._cfg.notify_on_session_end)
        self._chk_confirm_reset.setChecked(self._cfg.confirm_on_reset)
        self._chk_project_name.setChecked(self._cfg.show_project_name)

    def _save(self):
        self._cfg.idle_timeout_minutes  = self._spin_idle.value()
        self._cfg.pause_on_focus_loss   = self._chk_focus.isChecked()
        self._cfg.auto_start_on_open    = self._chk_autostart.isChecked()
        self._cfg.min_session_seconds   = self._spin_min_session.value()
        self._cfg.notify_on_session_end = self._chk_notify_session.isChecked()
        self._cfg.confirm_on_reset      = self._chk_confirm_reset.isChecked()
        self._cfg.show_project_name     = self._chk_project_name.isChecked()

        self._tracker.apply_idle_setting()

        if hasattr(self._tracker, "apply_project_name_setting"):
            self._tracker.apply_project_name_setting()

        self.accept()