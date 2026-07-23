"""
Thin wrapper around QSettings for Time Tracker preferences.
All values are read/written under the "TimeTrackerPlugin/" key-space.
Using bare QSettings() calls (no beginGroup) avoids group-nesting bugs
when the object is recreated across plugin reloads.

Qt 6 compatibility
------------------
QSettings API is unchanged between Qt 5 and Qt 6.  The boolean coercion
guard (string "true"/"false" → bool) is still necessary because QSettings
serialises bool as the string "true"/"false" in INI format on all platforms.
"""

_PREFIX = "TimeTrackerPlugin"

_DEFAULTS = {
    "idle_timeout_minutes": 10,
    "pause_on_focus_loss": False,
    "auto_start_on_open": False,
    "confirm_on_reset": True,
    "show_project_name": False,
    "min_session_seconds": 60,
    "notify_on_session_end": True,
    "daily_goal_hours": 0,  # 0 = disabled; >0 shows progress in toolbar
    "show_daily_progress": False,  # show daily goal progress bar in toolbar
    "language": "en",
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
        try:
            return int(v)
        except (TypeError, ValueError):
            return default
    if isinstance(default, float):
        try:
            return float(v)
        except (TypeError, ValueError):
            return default
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
        return max(0, min(480, _get("idle_timeout_minutes")))

    @idle_timeout_minutes.setter
    def idle_timeout_minutes(self, v: int):
        _set("idle_timeout_minutes", max(0, min(480, int(v))))

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
        return _get("confirm_on_reset")

    @confirm_on_reset.setter
    def confirm_on_reset(self, v: bool):
        _set("confirm_on_reset", bool(v))

    @property
    def show_project_name(self) -> bool:
        return _get("show_project_name")

    @show_project_name.setter
    def show_project_name(self, v: bool):
        _set("show_project_name", bool(v))

    @property
    def min_session_seconds(self) -> int:
        return max(0, min(300, _get("min_session_seconds")))

    @min_session_seconds.setter
    def min_session_seconds(self, v: int):
        _set("min_session_seconds", max(0, min(300, int(v))))

    @property
    def notify_on_session_end(self) -> bool:
        return _get("notify_on_session_end")

    @notify_on_session_end.setter
    def notify_on_session_end(self, v: bool):
        _set("notify_on_session_end", bool(v))

    @property
    def daily_goal_hours(self) -> int:
        """Daily work-hour goal (0 = disabled)."""
        return max(0, min(16, _get("daily_goal_hours")))

    @daily_goal_hours.setter
    def daily_goal_hours(self, v: int):
        _set("daily_goal_hours", max(0, min(16, int(v))))

    @property
    def show_daily_progress(self) -> bool:
        """Show the daily progress bar in the toolbar."""
        return _get("show_daily_progress")

    @show_daily_progress.setter
    def show_daily_progress(self, v: bool):
        _set("show_daily_progress", bool(v))

    @property
    def language(self) -> str:
        from .i18n import normalize_language

        return normalize_language(_get("language"))

    @language.setter
    def language(self, value: str):
        from .i18n import normalize_language

        _set("language", normalize_language(value))
