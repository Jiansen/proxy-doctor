"""py2app setup for proxy-doctor menu bar application."""

from setuptools import setup
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

APP = ["menu_bar.py"]
DATA_FILES = []
OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "LSUIElement": True,
        "CFBundleName": "proxy-doctor",
        "CFBundleDisplayName": "proxy-doctor",
        "CFBundleIdentifier": "com.jiansen.proxy-doctor",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "NSHumanReadableCopyright": "Copyright 2026 Jiansen He. MIT License.",
    },
    "packages": ["proxy_doctor", "rumps"],
    "includes": [
        "proxy_doctor.core",
        "proxy_doctor.editors",
        "proxy_doctor.cli",
    ],
    "excludes": [
        "proxy_doctor.mcp_server",
        "fastmcp",
    ],
    "iconfile": "",
}

setup(
    app=APP,
    name="proxy-doctor",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
