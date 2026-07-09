from pathlib import Path


def test_pyinstaller_spec_bundles_truststore_platform_modules():
    spec = Path(__file__).resolve().parents[2] / "packaging" / "stl-studio.spec"
    text = spec.read_text(encoding="utf-8")

    for module in (
        "truststore",
        "truststore._api",
        "truststore._macos",
        "truststore._openssl",
        "truststore._ssl_constants",
        "truststore._windows",
    ):
        assert f'"{module}"' in text
