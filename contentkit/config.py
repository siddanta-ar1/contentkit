"""User settings in ~/.contentkit/config.yaml (e.g. `private: true`)."""
from pathlib import Path

import yaml

PATH = Path.home() / ".contentkit" / "config.yaml"


def load():
    return (yaml.safe_load(PATH.read_text()) or {}) if PATH.exists() else {}


def get(key, default=None):
    return load().get(key, default)


def set_value(key, value):
    data = load()
    data[key] = value
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(yaml.safe_dump(data, sort_keys=True))
    return data


def private():
    """Private mode: everything stays on this machine, so downloads are labelled for private
    use instead of being flagged as uncleared."""
    return bool(get("private", False))
