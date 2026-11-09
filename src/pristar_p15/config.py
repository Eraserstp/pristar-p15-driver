"""Configuration for the Pristar P15 driver."""

import configparser
import os

DEFAULTS = {
    "mac": "",
    "helper": "/usr/lib/pristar-p15/p15-leconnect",
    "adapter": "hci0",
    "packet": "95",
    "tick_ms": "30",
    "density": "2",
    "paper_type": "gap",
    "feed_dots": "100",
    "dither": "fs",
    "rotation": "270",
    "head_margin": "2",
    "feed_start": "2",
    "feed_end": "6",
    "x_shift": "0",
    "keep_alive": "false",
    "connect_timeout": "20",
}

CONFIG_PATH = os.environ.get("PRISTAR_P15_CONF", "/etc/pristar-p15.conf")


def load(path=None):
    """Return a dict with defaults overridden by /etc/pristar-p15.conf."""
    cfg = dict(DEFAULTS)
    cp = configparser.ConfigParser()
    try:
        cp.read(path or CONFIG_PATH)
    except (configparser.Error, OSError):
        return cfg
    for section in cp.sections():
        for key, value in cp.items(section):
            key = key.replace("-", "_")
            if key in cfg:
                cfg[key] = value.strip()
    return cfg


def as_int(cfg, key, default=0):
    try:
        return int(cfg.get(key, default))
    except (TypeError, ValueError):
        return default


def as_bool(cfg, key, default=False):
    value = str(cfg.get(key, default)).strip().lower()
    return value in ("1", "true", "yes", "on")
