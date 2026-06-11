"""Profile persistence for Bulk Settings.

Profiles are named snapshots of all bulk settings stored as QSettings
groups under ``bulk/profiles/<name>/``.  Each group contains the same
keys that _save_bulk_config writes to the flat QSettings space.
"""

from __future__ import annotations

from PyQt6.QtCore import QSettings

from pmgen.ui.workers import BulkConfig

DEFAULT_PROFILE_NAME = "Default"
_PROFILES_ROOT = "bulk/profiles"
_LAST_PROFILE_KEY = "bulk/last_profile"

# ---------------------------------------------------------------------------
# Key list — mirrors the keys written by MainWindow._save_bulk_config.
# Each entry is the QSettings suffix (e.g. "top_n") and the BulkConfig field
# name (e.g. "top_n").  We use this mapping to avoid duplicating key names.
# ---------------------------------------------------------------------------
_PROFILE_FIELDS: list[tuple[str, str]] = [
    # (settings_key_suffix,  config_field_name)
    ("top_n", "top_n"),
    ("out_dir", "out_dir"),
    ("pool_size", "pool_size"),
    ("blacklist", "blacklist"),
    ("custom_08_name", "custom_08_name"),
    ("custom_08_code", "custom_08_code"),
    ("custom_08_sub", "custom_08_sub"),
    ("custom_05_name", "custom_05_name"),
    ("custom_05_code", "custom_05_code"),
    ("custom_05_sub", "custom_05_sub"),
    ("generate_pdfs", "generate_pdfs"),
    ("machine_filter", "machine_filter"),
    ("unpack_filter_enabled", "unpack_filter_enabled"),
    ("unpack_extra_months", "unpack_extra_months"),
    ("unpack_min_filter_enabled", "unpack_min_filter_enabled"),
    ("unpack_min_months", "unpack_min_months"),
]


def _snapshot_current_settings() -> BulkConfig:
    """Build a BulkConfig from the current flat QSettings values.

    This mirrors ``MainWindow._get_bulk_config`` but works standalone.
    """
    s = QSettings()

    def _int(key: str, default: int = 0) -> int:
        try:
            return int(s.value(key, default, int))
        except (TypeError, ValueError):
            return default

    return BulkConfig(
        top_n=max(1, min(9999, _int("bulk/top_n", 25))),
        out_dir=s.value("bulk/out_dir", "", str) or "",
        pool_size=max(1, min(16, _int("bulk/pool_size", 4))),
        blacklist=_parse_blacklist(s.value("bulk/blacklist", "", str) or ""),
        custom_08_name=s.value("bulk/custom_08_name", "", str) or "",
        custom_08_code=_int("bulk/custom_08_code"),
        custom_08_sub=_int("bulk/custom_08_sub"),
        custom_05_name=s.value("bulk/custom_05_name", "", str) or "",
        custom_05_code=_int("bulk/custom_05_code"),
        custom_05_sub=_int("bulk/custom_05_sub"),
        generate_pdfs=bool(s.value("bulk/generate_pdfs", True, bool)),
        machine_filter=s.value("bulk/machine_filter", "both", str),
        unpack_filter_enabled=bool(s.value("bulk/unpack_filter_enabled", False, bool)),
        unpack_extra_months=_int("bulk/unpack_extra_months"),
        unpack_min_filter_enabled=bool(s.value("bulk/unpack_min_filter_enabled", False, bool)),
        unpack_min_months=_int("bulk/unpack_min_months"),
    )


def _parse_blacklist(raw: str) -> list[str]:
    import re

    return [line.strip().upper() for line in re.split(r"[,\n]+", raw) if line.strip()]


def _serialize_blacklist(items: list[str] | None) -> str:
    return "\n".join(items or [])


def _profile_group(name: str) -> str:
    return f"{_PROFILES_ROOT}/{name}"


def list_profile_names() -> list[str]:
    """Return sorted profile names.  Auto-creates "Default" if none exist."""
    names = _raw_profile_names()
    if not names:
        _ensure_default_profile()
        names = [DEFAULT_PROFILE_NAME]
    return sorted(names, key=str.lower)


def _ensure_default_profile() -> None:
    """Create the Default profile from current flat settings if it does not exist."""
    if DEFAULT_PROFILE_NAME in _raw_profile_names():
        return
    save_profile(DEFAULT_PROFILE_NAME, _snapshot_current_settings())


def _raw_profile_names() -> list[str]:
    """Discover profile names by scanning all QSettings keys."""
    s = QSettings()
    prefix = f"{_PROFILES_ROOT}/"
    names: set[str] = set()
    for key in s.allKeys():
        if key.startswith(prefix):
            rest = key[len(prefix):]
            name = rest.split("/", 1)[0]
            if name:
                names.add(name)
    return sorted(names, key=str.lower)


def load_profile(name: str) -> BulkConfig:
    """Load a profile from QSettings into a BulkConfig."""
    s = QSettings()
    group_prefix = f"{_profile_group(name)}/"
    kwargs: dict[str, object] = {}
    # Read each field using its full key path so we don't depend on beginGroup.
    for key_suffix, field_name in _PROFILE_FIELDS:
        full_key = f"{group_prefix}{key_suffix}"
        if field_name == "blacklist":
            kwargs[field_name] = _parse_blacklist(s.value(full_key, "", str) or "")
        elif field_name.endswith("_enabled") or field_name == "generate_pdfs":
            kwargs[field_name] = bool(s.value(full_key, field_name == "generate_pdfs", bool))
        elif field_name in ("out_dir", "custom_08_name", "custom_05_name", "machine_filter"):
            kwargs[field_name] = s.value(full_key, "", str) or ""
        else:
            kwargs[field_name] = int(s.value(full_key, 0, int))
    return BulkConfig(**kwargs)


def save_profile(name: str, cfg: BulkConfig) -> None:
    """Write all BulkConfig fields under ``bulk/profiles/<name>/``."""
    s = QSettings()
    group_prefix = f"{_profile_group(name)}/"
    for key_suffix, field_name in _PROFILE_FIELDS:
        full_key = f"{group_prefix}{key_suffix}"
        value = getattr(cfg, field_name)
        if field_name == "blacklist":
            s.setValue(full_key, _serialize_blacklist(value))
        elif isinstance(value, bool):
            s.setValue(full_key, bool(value))
        elif isinstance(value, int):
            s.setValue(full_key, int(value))
        else:
            s.setValue(full_key, str(value or ""))
    s.sync()


def delete_profile(name: str) -> None:
    """Remove a profile.  ``"Default"`` cannot be deleted."""
    if name == DEFAULT_PROFILE_NAME:
        raise ValueError("The Default profile cannot be deleted.")
    s = QSettings()
    prefix = f"{_profile_group(name)}/"
    for key in list(s.allKeys()):
        if key.startswith(prefix):
            s.remove(key)
    s.sync()


def get_last_profile_name() -> str:
    """Return the last-used profile name, falling back to Default."""
    name = QSettings().value(_LAST_PROFILE_KEY, "", str) or ""
    if not name or name not in list_profile_names():
        return DEFAULT_PROFILE_NAME
    return name


def set_last_profile_name(name: str) -> None:
    """Persist the last-used profile name."""
    QSettings().setValue(_LAST_PROFILE_KEY, name)
