# PyInstaller spec: single-file binary of the Messer on-prem connector agent.
# Build (from the repository root, in a virtualenv with the agent installed):
#   pip install pyinstaller && pyinstaller services/connector-agent/messer-connector-agent.spec
# Output: dist/messer-connector-agent
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = [
    *collect_submodules("messer_connectors.sql"),
    *collect_submodules("websockets"),
    *collect_submodules("psycopg"),
    "psycopg_binary",
    "pymysql",
    "pytds",
    "yaml",
]

# The agent only uses messer_connectors.sql (stdlib + drivers); keep the platform kernel out of the binary.
excludes = [
    "messer_common", "messer_api", "messer", "sqlalchemy", "redis", "arq", "alembic", "fastapi", "starlette",
    "uvicorn", "pydantic", "jsonschema", "httpx", "tkinter", "numpy", "pandas",
]

a = Analysis(
    ["src/messer_connector_agent/__main__.py"],
    pathex=["src", "../../packages/connectors/src"],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="messer-connector-agent",
    debug=False,
    strip=False,
    upx=False,
    console=True,
)
