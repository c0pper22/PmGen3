"""Test harness isolation for Qt and Python writable runtime paths."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PyQt6.QtCore import QStandardPaths

_RUNTIME_ROOT = Path.cwd() / ".test_runtime"
_APPDATA = _RUNTIME_ROOT / "appdata"
_CACHE = _RUNTIME_ROOT / "cache"
_TEMP = _RUNTIME_ROOT / "temp"

for path in (_APPDATA, _CACHE, _TEMP):
    path.mkdir(parents=True, exist_ok=True)

os.environ["APPDATA"] = str(_APPDATA)
os.environ["LOCALAPPDATA"] = str(_CACHE)
os.environ["TEMP"] = str(_TEMP)
os.environ["TMP"] = str(_TEMP)
tempfile.tempdir = str(_TEMP)

_original_writable_location = QStandardPaths.writableLocation


def _writable_location(location):
    if location == QStandardPaths.StandardLocation.AppDataLocation:
        return str(_APPDATA)
    if location == QStandardPaths.StandardLocation.CacheLocation:
        return str(_CACHE)
    if location == QStandardPaths.StandardLocation.TempLocation:
        return str(_TEMP)
    return _original_writable_location(location)


QStandardPaths.writableLocation = staticmethod(_writable_location)
