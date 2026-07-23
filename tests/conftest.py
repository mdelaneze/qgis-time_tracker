import os
import sys

import pytest


@pytest.fixture(scope="session", autouse=True)
def qgis_application():
    sys.path.insert(0, os.getcwd())
    plugins_path = "/usr/share/qgis/python/plugins"
    if os.path.isdir(plugins_path):
        sys.path.insert(0, plugins_path)

    from qgis.core import QgsApplication

    created_here = QgsApplication.instance() is None
    app = QgsApplication([], False) if created_here else QgsApplication.instance()
    if created_here:
        app.initQgis()
    yield app
    # Não encerra uma instância criada pelo runner QGIS.
