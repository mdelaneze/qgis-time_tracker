"""
Thin wrapper around QSettings for Time Tracker preferences.
All values are read/written under the "TimeTrackerPlugin/" key-space.
Using bare QSettings() calls (no beginGroup) avoids group-nesting bugs
when the object is recreated across plugin reloads.
"""

_PREFIX = "TimeTrackerPlugin"

_DEFAULTS = {
    "idle_timeout_minutes": 10,
    "pause_on_focus_loss": False,
    "auto_start_on_open": False,
}


def _qs():
    from qgis.PyQt.QtCore import QSettings
    return QSettings()


def _key(name):
    return f"{_PREFIX}/{name}"


def _get(name):
    default = _DEFAULTS.get(name)
    v = _qs().value(_key(name), default)
    if isinstance(default, bool):
        if isinstance(v, str):
            return v.lower() == "true"
        return bool(v)
    if isinstance(default, int):
        return int(v)
    return v


def _set(name, value):
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
    def idle_timeout_minutes(self):
        return _get("idle_timeout_minutes")

    @idle_timeout_minutes.setter
    def idle_timeout_minutes(self, v):
        _set("idle_timeout_minutes", int(v))

    @property
    def pause_on_focus_loss(self):
        return _get("pause_on_focus_loss")

    @pause_on_focus_loss.setter
    def pause_on_focus_loss(self, v):
        _set("pause_on_focus_loss", bool(v))

    @property
    def auto_start_on_open(self):
        return _get("auto_start_on_open")

    @auto_start_on_open.setter
    def auto_start_on_open(self, v):
        _set("auto_start_on_open", bool(v))