from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QSpinBox, QCheckBox,
    QDialogButtonBox, QGroupBox,
)
from ..core.tracker import TrackerState


class SettingsDialog(QDialog):

    def __init__(self, settings, tracker, parent=None):
        super().__init__(parent)
        self._cfg     = settings
        self._tracker = tracker
        self.setWindowTitle("Time Tracker – Settings")
        self.setMinimumWidth(380)
        self._build_ui()
        self._load()

    def _build_ui(self):
        root = QVBoxLayout(self)

        grp_pause = QGroupBox("Auto-Pause")
        form = QFormLayout(grp_pause)

        self._spin_idle = QSpinBox()
        self._spin_idle.setRange(0, 480)
        self._spin_idle.setSuffix(" min")
        self._spin_idle.setSpecialValueText("Disabled")
        self._spin_idle.setToolTip(
            "Automatically pause after this many minutes of inactivity.\n"
            "Set to 0 to disable."
        )
        form.addRow("Idle timeout:", self._spin_idle)

        self._chk_focus = QCheckBox("Pause when QGIS loses focus or is minimised")
        form.addRow(self._chk_focus)
        root.addWidget(grp_pause)

        grp_start = QGroupBox("Auto-Start")
        form2 = QFormLayout(grp_start)
        self._chk_autostart = QCheckBox(
            "Start tracking automatically when a project is opened"
        )
        form2.addRow(self._chk_autostart)
        root.addWidget(grp_start)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _load(self):
        self._spin_idle.setValue(self._cfg.idle_timeout_minutes)
        self._chk_focus.setChecked(self._cfg.pause_on_focus_loss)
        self._chk_autostart.setChecked(self._cfg.auto_start_on_open)

    def _save(self):
        self._cfg.idle_timeout_minutes = self._spin_idle.value()
        self._cfg.pause_on_focus_loss  = self._chk_focus.isChecked()
        self._cfg.auto_start_on_open   = self._chk_autostart.isChecked()

        # Apply idle timer immediately without restart
        if (
            self._cfg.idle_timeout_minutes > 0
            and self._tracker.state == TrackerState.RUNNING
        ):
            self._tracker._idle_timer.start()
        else:
            self._tracker._idle_timer.stop()

        self.accept()