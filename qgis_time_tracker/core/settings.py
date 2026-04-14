"""
Thin wrapper around QSettings for Time Tracker preferences.
All values are read/written under the "TimeTrackerPlugin/" key-space.
Using bare QSettings() calls (no beginGroup) avoids group-nesting bugs
when the object is recreated across plugin reloads.
"""

_PREFIX = "TimeTrackerPlugin"

_DEFAULTS = {
    "idle_timeout_minutes":  10,
    "pause_on_focus_loss":   False,
    "auto_start_on_open":    False,
    "confirm_on_reset":      True,
    "show_project_name":     False,
    "min_session_seconds":   0,      # sessões menores que isso são descartadas
    "notify_on_session_end": False,  # notificação no messageBar ao encerrar sessão
}


def _qs():
    from qgis.PyQt.QtCore import QSettings
    return QSettings()


def _key(name: str) -> str:
    return f"{_PREFIX}/{name}"


def _get(name: str):
    default = _DEFAULTS.get(name)
    v = _qs().value(_key(name), default)
    if isinstance(default, bool):
        if isinstance(v, str):
            return v.lower() == "true"
        return bool(v)
    if isinstance(default, int):
        return int(v)
    return v


def _set(name: str, value):
    s = _qs()
    s.setValue(_key(name), value)
    s.sync()


class TrackerSettings:
    """
    Mutable, always-fresh settings proxy.
    Reads hit QSettings on every access so changes are immediately visible
    even when multiple instances exist (settings dialog vs. plugin).
    """

    @property
    def idle_timeout_minutes(self) -> int:
        return _get("idle_timeout_minutes")

    @idle_timeout_minutes.setter
    def idle_timeout_minutes(self, v: int):
        _set("idle_timeout_minutes", int(v))

    @property
    def pause_on_focus_loss(self) -> bool:
        return _get("pause_on_focus_loss")

    @pause_on_focus_loss.setter
    def pause_on_focus_loss(self, v: bool):
        _set("pause_on_focus_loss", bool(v))

    @property
    def auto_start_on_open(self) -> bool:
        return _get("auto_start_on_open")

    @auto_start_on_open.setter
    def auto_start_on_open(self, v: bool):
        _set("auto_start_on_open", bool(v))

    @property
    def confirm_on_reset(self) -> bool:
        """Show confirmation dialog before resetting a project's time counter."""
        return _get("confirm_on_reset")

    @confirm_on_reset.setter
    def confirm_on_reset(self, v: bool):
        _set("confirm_on_reset", bool(v))

    @property
    def show_project_name(self) -> bool:
        """Show the active project name label in the toolbar widget."""
        return _get("show_project_name")

    @show_project_name.setter
    def show_project_name(self, v: bool):
        _set("show_project_name", bool(v))

    @property
    def min_session_seconds(self) -> int:
        """Sessions shorter than this are discarded on pause/stop."""
        return _get("min_session_seconds")

    @min_session_seconds.setter
    def min_session_seconds(self, v: int):
        _set("min_session_seconds", int(v))

    @property
    def notify_on_session_end(self) -> bool:
        """Show a messageBar notification when a session ends."""
        return _get("notify_on_session_end")

    @notify_on_session_end.setter
    def notify_on_session_end(self, v: bool):
        _set("notify_on_session_end", bool(v))
