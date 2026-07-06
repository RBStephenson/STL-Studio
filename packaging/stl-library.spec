# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for STL Studio standalone build.
#
# Run from the PROJECT ROOT (not this directory):
#   pyinstaller packaging/stl-library.spec
#
# The frontend must be built first:
#   cd frontend && npm run build
#
# Output: dist/stl-library  (or dist/stl-library.exe on Windows)

from pathlib import Path

ROOT = Path(".").resolve()
BACKEND = ROOT / "backend"
FRONTEND_DIST = ROOT / "frontend" / "dist"

block_cipher = None

# Phase 2 (STUDIO-72): the desktop shell is now Electron, which owns the window
# and spawns this exe as a headless sidecar. The old pywebview / clr_loader /
# pythonnet bundling is gone, and the exe is built windowless (console=False).

a = Analysis(
    [str(ROOT / "packaging" / "standalone.py")],
    pathex=[str(BACKEND)],
    binaries=[],
    datas=[
        # Bundle the built React frontend
        (str(FRONTEND_DIST), "dist"),
        # Bundle the backend app package (needed for relative imports)
        (str(BACKEND / "app"), "app"),
        # Alembic migrations (ini + env + versions)
        (str(BACKEND / "alembic.ini"), "."),
        (str(BACKEND / "alembic"), "alembic"),
    ],
    hiddenimports=[
        # uvicorn internals that PyInstaller misses
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        # FastAPI / Starlette
        "starlette.staticfiles",
        "starlette.routing",
        "aiofiles",
        "aiofiles.os",
        "aiofiles.threadpool",
        # SQLAlchemy dialects
        "sqlalchemy.dialects.sqlite",
        "sqlalchemy.dialects.sqlite.pysqlite",
        # Pydantic
        "pydantic",
        "pydantic_settings",
        "pydantic.deprecated.class_validators",
        # Scraper / HTTP
        "bs4",
        "httpx",
        "httpcore",
        "h11",
        "truststore",
        "truststore._api",
        "truststore._macos",
        "truststore._openssl",
        "truststore._ssl_constants",
        "truststore._windows",
        # Other deps
        "multipart",
        "python_multipart",
        "apscheduler",
        "apscheduler.schedulers.background",
        "watchdog",
        "watchdog.observers",
        "watchdog.observers.polling",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # NOTE: do not exclude "unittest" — numpy.testing imports it at module load,
    # and the painting colormatch path pulls in skimage -> scipy -> numpy, so a
    # frozen build without unittest crashes at startup (STUDIO-100).
    excludes=["tkinter", "test"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="stl-library",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,           # UPX can trigger AV false-positives; keep off by default
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,       # Windowless: Electron owns the UI; stdout/stderr are piped to the sidecar log
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
