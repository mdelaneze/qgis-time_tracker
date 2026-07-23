"""
SettingsDialog – Time Tracker preferences.

"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)

from ..core.i18n import LANGUAGE_NAMES, SUPPORTED_LANGUAGES, tr

# ── Qt5 / Qt6 enum compat helpers ─────────────────────────────────────────────


def _qt(cls, *chain, fallback=None):
    """Walk attribute chain on cls, return first match or fallback."""
    obj = cls
    for attr in chain:
        obj = getattr(obj, attr, None)
        if obj is None:
            return fallback
    return obj if obj is not None else fallback


def _horizontal():
    return _qt(Qt, "Orientation", "Horizontal") or _qt(Qt, "Horizontal")


def _ticks_below():
    return _qt(QSlider, "TickPosition", "TicksBelow") or _qt(QSlider, "TicksBelow")


def _btn(*names):
    """Resolve QDialogButtonBox standard button flags for PyQt5 and PyQt6."""
    result = None
    for name in names:
        v = _qt(QDialogButtonBox, "StandardButton", name) or _qt(QDialogButtonBox, name)
        if v is not None:
            result = v if result is None else (result | v)
    return result


# ── dialog ─────────────────────────────────────────────────────────────────────


class SettingsDialog(QDialog):

    def __init__(self, settings, tracker, parent=None):
        super().__init__(parent)
        self._cfg = settings
        self._tracker = tracker
        self._language = self._cfg.language
        self.setWindowTitle(self._t("Time Tracker – Settings"))
        self.setMinimumWidth(460)
        self._build_ui()
        self._load()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)

        # ── Auto-Pause ────────────────────────────────────────────────────────
        grp_pause = QGroupBox(self._t("Auto-pause"))
        form = QFormLayout(grp_pause)

        self._spin_idle = QSpinBox()
        self._spin_idle.setRange(0, 480)
        self._spin_idle.setSuffix(" min")
        self._spin_idle.setSpecialValueText(self._t("Disabled"))
        self._spin_idle.setToolTip(
            self._t(
                "Pause after this period without activity in QGIS.\n"
                "Use 0 to disable."
            )
        )
        form.addRow(self._t("Idle timeout:"), self._spin_idle)

        self._chk_focus = QCheckBox(
            self._t("Pause when QGIS is minimized or loses focus")
        )
        form.addRow(self._chk_focus)
        root.addWidget(grp_pause)

        # ── Auto-Start ────────────────────────────────────────────────────────
        grp_start = QGroupBox(self._t("Automatic start"))
        form2 = QFormLayout(grp_start)
        self._chk_autostart = QCheckBox(
            self._t("Start tracking automatically when a project is opened")
        )
        form2.addRow(self._chk_autostart)
        root.addWidget(grp_start)

        # ── Sessions ──────────────────────────────────────────────────────────
        grp_sess = QGroupBox(self._t("Sessions"))
        form3 = QFormLayout(grp_sess)

        self._spin_min_session = QSpinBox()
        self._spin_min_session.setRange(0, 300)
        self._spin_min_session.setSuffix(" s")
        self._spin_min_session.setSpecialValueText(self._t("Record all"))
        self._spin_min_session.setToolTip(
            self._t(
                "Sessions shorter than this value are discarded when paused or stopped.\n"
                "This helps ignore accidental starts.\nUse 0 to record all."
            )
        )
        form3.addRow(self._t("Minimum duration:"), self._spin_min_session)

        slider_row = QHBoxLayout()
        self._sld_min_session = QSlider(_horizontal())
        self._sld_min_session.setRange(0, 300)
        self._sld_min_session.setTickInterval(60)
        self._sld_min_session.setTickPosition(_ticks_below())
        self._sld_min_session.setToolTip(
            self._t("Drag to adjust the minimum duration.")
        )
        self._spin_min_session.valueChanged.connect(self._sld_min_session.setValue)
        self._sld_min_session.valueChanged.connect(self._spin_min_session.setValue)
        slider_row.addWidget(QLabel("0 s"))
        slider_row.addWidget(self._sld_min_session, 1)
        slider_row.addWidget(QLabel("5 min"))
        form3.addRow(slider_row)

        self._chk_notify_session = QCheckBox(
            self._t("Show a notification when a session ends")
        )
        self._chk_notify_session.setToolTip(
            self._t(
                "Shows the session duration in the QGIS message bar when it is "
                "paused or stopped."
            )
        )
        form3.addRow(self._chk_notify_session)
        root.addWidget(grp_sess)

        # ── Daily Goal ────────────────────────────────────────────────────────
        grp_goal = QGroupBox(self._t("Daily goal"))
        form4 = QFormLayout(grp_goal)

        self._spin_goal = QSpinBox()
        self._spin_goal.setRange(0, 16)
        self._spin_goal.setSuffix(" h")
        self._spin_goal.setSpecialValueText(self._t("No goal"))
        self._spin_goal.setToolTip(
            self._t(
                "Set a daily work goal.\n"
                "The integrated bar will show today's progress.\nUse 0 to disable."
            )
        )
        form4.addRow(self._t("Daily goal") + ":", self._spin_goal)

        self._chk_show_progress = QCheckBox(
            self._t("Show daily progress in the toolbar")
        )
        self._chk_show_progress.setToolTip(
            self._t(
                "Shows below the timer how much of today's goal has been completed."
            )
        )
        form4.addRow(self._chk_show_progress)
        root.addWidget(grp_goal)

        # ── Interface ─────────────────────────────────────────────────────────
        grp_ui = QGroupBox(self._t("Interface"))
        form5 = QFormLayout(grp_ui)

        self._language_combo = QComboBox()
        for code in SUPPORTED_LANGUAGES:
            self._language_combo.addItem(LANGUAGE_NAMES[code], code)
        form5.addRow(self._t("Language") + ":", self._language_combo)

        self._chk_confirm_reset = QCheckBox(
            self._t("Ask for confirmation before resetting a project's time")
        )
        self._chk_confirm_reset.setToolTip(
            self._t("When enabled, asks for confirmation before resetting the timer.")
        )
        form5.addRow(self._chk_confirm_reset)

        self._chk_project_name = QCheckBox(
            self._t("Show the project name in the toolbar")
        )
        self._chk_project_name.setToolTip(
            self._t("Shows the active project name next to the timer.")
        )
        form5.addRow(self._chk_project_name)
        root.addWidget(grp_ui)

        # ── Buttons ───────────────────────────────────────────────────────────
        btns = QDialogButtonBox(_btn("Ok", "Cancel"))
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
        self._spin_goal.setValue(self._cfg.daily_goal_hours)
        self._chk_show_progress.setChecked(self._cfg.show_daily_progress)
        index = self._language_combo.findData(self._cfg.language)
        self._language_combo.setCurrentIndex(max(0, index))

    def _save(self):
        self._cfg.idle_timeout_minutes = self._spin_idle.value()
        self._cfg.pause_on_focus_loss = self._chk_focus.isChecked()
        self._cfg.auto_start_on_open = self._chk_autostart.isChecked()
        self._cfg.min_session_seconds = self._spin_min_session.value()
        self._cfg.notify_on_session_end = self._chk_notify_session.isChecked()
        self._cfg.confirm_on_reset = self._chk_confirm_reset.isChecked()
        self._cfg.show_project_name = self._chk_project_name.isChecked()
        self._cfg.daily_goal_hours = self._spin_goal.value()
        self._cfg.show_daily_progress = self._chk_show_progress.isChecked()
        self._cfg.language = self._language_combo.currentData()

        self._tracker.apply_idle_setting()

        if hasattr(self._tracker, "apply_project_name_setting"):
            self._tracker.apply_project_name_setting()

        self.accept()

    def _t(self, text, **values):
        return tr(text, self._language, **values)
