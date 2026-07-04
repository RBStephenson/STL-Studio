"""Launch/config tests for the headless standalone entry point (STUDIO-72).

Only the pure helpers are covered — actually serving needs a live event loop and
is verified by the CI build + manual run. The module is loaded by file path
because packaging/ is not an importable package, and it must stay import-light
(no app/DB build at module scope) for this to work.
"""
import importlib.util
import signal
from pathlib import Path

import pytest

_STANDALONE = Path(__file__).resolve().parents[2] / "packaging" / "standalone.py"


@pytest.fixture(scope="module")
def standalone():
    spec = importlib.util.spec_from_file_location("standalone_under_test", _STANDALONE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- paths -----------------------------------------------------------------

def test_frontend_dist_resolves_to_project_when_unfrozen(standalone):
    p = standalone._frontend_dist()
    assert p.name == "dist"
    assert "frontend" in str(p)


def test_user_data_dir_is_app_named(standalone):
    assert standalone._user_data_dir().name == "STL-Inventory"


# --- port resolution -------------------------------------------------------

def test_port_defaults_when_nothing_set(standalone):
    assert standalone.resolve_port(None, env={}) == standalone.DEFAULT_PORT


def test_cli_port_takes_precedence(standalone):
    assert standalone.resolve_port(9000, env={"STL_PORT": "7000"}) == 9000


def test_env_port_used_when_no_cli(standalone):
    assert standalone.resolve_port(None, env={"STL_PORT": "7000"}) == 7000


def test_invalid_env_port_falls_back_to_default(standalone):
    assert standalone.resolve_port(None, env={"STL_PORT": "notaport"}) == standalone.DEFAULT_PORT


def test_parser_reads_port_and_open_browser(standalone):
    args = standalone.build_parser().parse_args(["--port", "1234", "--open-browser"])
    assert args.port == 1234
    assert args.open_browser is True


def test_parser_defaults(standalone):
    args = standalone.build_parser().parse_args([])
    assert args.port is None
    assert args.open_browser is False


# --- graceful shutdown -----------------------------------------------------

class _FakeServer:
    def __init__(self):
        self.should_exit = False


def test_sigterm_handler_requests_graceful_exit(standalone):
    server = _FakeServer()
    handler = standalone._make_sigterm_handler(server)
    handler(signal.SIGTERM, None)
    assert server.should_exit is True


def test_install_sigterm_registers_handler(standalone):
    server = _FakeServer()
    previous = signal.getsignal(signal.SIGTERM)
    try:
        standalone.install_sigterm(server)
        assert signal.getsignal(signal.SIGTERM) is not previous
        # The registered handler drives our server, not the old one.
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        assert server.should_exit is True
    finally:
        signal.signal(signal.SIGTERM, previous)


# --- headless: no window/browser decision surface remains ------------------

def test_no_window_decision_helpers_remain(standalone):
    """The pywebview window path is gone in Phase 2; these must not resurface."""
    assert not hasattr(standalone, "should_use_window")
    assert not hasattr(standalone, "_serve_background")
