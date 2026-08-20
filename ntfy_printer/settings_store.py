"""Persistent, hot-reloadable customization settings for the web UI.

Priority symbols, banner styles, icon sets, and emoji overrides are stored as
JSON on disk (config.SETTINGS_FILE) and applied *in place* onto the mutable
dicts already exposed by config.py / emoji_map.py. Because dicts are mutated
in place (clear + update) rather than reassigned, every module that already
holds a reference to e.g. config.PRIORITY_SYMBOLS sees changes immediately —
no restart required.
"""

import json
import logging
import os

from . import config
from .emoji_map import EMOJI_TAG_MAP


def _defaults():
    """Snapshot of the built-in defaults, used to seed/merge saved settings."""
    return {
        "priority_symbols": {k: dict(v) for k, v in config.PRIORITY_SYMBOLS.items()},
        "priority_banner_styles": {k: dict(v) for k, v in config.PRIORITY_BANNER_STYLES.items()},
        "icon_priority": dict(config.ICON_PRIORITY),
        "icon_status": dict(config.ICON_STATUS),
        "icon_type": dict(config.ICON_TYPE),
        "emoji_map": dict(config.EMOJI_MAP),
        "tag_emoji_overrides": {},
    }


def load():
    """Load settings from disk (merged over defaults) and apply them.

    Returns the merged settings dict (handy for the web UI to render forms).
    """
    data = _defaults()
    if os.path.exists(config.SETTINGS_FILE):
        try:
            with open(config.SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for key in data:
                if isinstance(saved.get(key), dict):
                    data[key].update(saved[key])
        except Exception:
            logging.exception("Failed to load web UI settings from %s; using defaults", config.SETTINGS_FILE)
    apply(data)
    return data


def apply(data):
    """Mutate the live config/emoji_map dicts in place so changes take effect immediately."""
    priority_symbols = data.get("priority_symbols", {})
    config.PRIORITY_SYMBOLS.clear()
    config.PRIORITY_SYMBOLS.update(priority_symbols)

    banner_styles = {}
    for level, style in data.get("priority_banner_styles", {}).items():
        style = dict(style)
        if "fill" in style:
            style["fill"] = tuple(style["fill"])
        banner_styles[level] = style
    config.PRIORITY_BANNER_STYLES.clear()
    config.PRIORITY_BANNER_STYLES.update(banner_styles)

    config.ICON_PRIORITY.clear()
    config.ICON_PRIORITY.update(data.get("icon_priority", {}))

    config.ICON_STATUS.clear()
    config.ICON_STATUS.update(data.get("icon_status", {}))

    config.ICON_TYPE.clear()
    config.ICON_TYPE.update(data.get("icon_type", {}))

    config.EMOJI_MAP.clear()
    config.EMOJI_MAP.update(data.get("emoji_map", {}))

    EMOJI_TAG_MAP.update(data.get("tag_emoji_overrides", {}))


def save(data):
    """Persist settings to disk and apply them immediately."""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    serializable = json.loads(json.dumps(data))  # normalize tuples -> lists, etc.
    with open(config.SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(serializable, f, indent=2, ensure_ascii=False, sort_keys=True)
    apply(serializable)


def current():
    """Return the current in-memory state in the same shape as load()/save()."""
    return {
        "priority_symbols": {k: dict(v) for k, v in config.PRIORITY_SYMBOLS.items()},
        "priority_banner_styles": {
            k: {**v, "fill": list(v.get("fill", (200, 200, 200)))}
            for k, v in config.PRIORITY_BANNER_STYLES.items()
        },
        "icon_priority": dict(config.ICON_PRIORITY),
        "icon_status": dict(config.ICON_STATUS),
        "icon_type": dict(config.ICON_TYPE),
        "emoji_map": dict(config.EMOJI_MAP),
        "tag_emoji_overrides": _tag_overrides(),
    }


def _tag_overrides():
    """Best-effort: overrides are whatever was last saved to disk (not diffable in memory)."""
    if os.path.exists(config.SETTINGS_FILE):
        try:
            with open(config.SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            return saved.get("tag_emoji_overrides", {})
        except Exception:
            return {}
    return {}
