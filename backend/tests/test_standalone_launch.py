"""Launch-decision tests for the standalone desktop shell (#463).

Only the pure decision/path helpers are covered — actually opening a native
window needs a GUI backend and is verified by the CI build + manual run. The
module is loaded by file path because packaging/ is not an importable package,
and it must stay import-light (no app/DB build at module scope) for this to work.
"""
import importlib.util
from pathlib import Path

import pytest

_STANDALONE = Path(__file__).resolve().parents[2] / "packaging" / "standalone.py"


@pytest.fixture(scope="module")
def standalone():
    spec = importlib.util.spec_from_file_location("standalone_under_test", _STANDALONE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_window_used_by_default(standalone):
    assert standalone.should_use_window(env={}, webview_available=True) is True


def test_opt_out_env_forces_browser(standalone):
    assert standalone.should_use_window(env={"STL_NO_WINDOW": "1"}, webview_available=True) is False


def test_missing_webview_forces_browser(standalone):
    assert standalone.should_use_window(env={}, webview_available=False) is False


def test_frontend_dist_resolves_to_project_when_unfrozen(standalone):
    p = standalone._frontend_dist()
    assert p.name == "dist"
    assert "frontend" in str(p)


def test_user_data_dir_is_app_named(standalone):
    assert standalone._user_data_dir().name == "STL-Inventory"
