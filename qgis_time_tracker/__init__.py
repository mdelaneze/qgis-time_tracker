def classFactory(iface):
    from .time_tracker_plugin import TimeTrackerPlugin
    return TimeTrackerPlugin(iface)