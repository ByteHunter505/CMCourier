"""Smoke tests: minimal proof that the package is installed and importable."""

import re

import cmcourier


def test_package_imports() -> None:
    """The package must be importable after ``pip install -e .[dev]``."""
    assert cmcourier is not None


def test_version_is_set() -> None:
    """The package must expose a SemVer-compatible ``__version__`` string."""
    version = getattr(cmcourier, "__version__", None)
    assert isinstance(version, str), "cmcourier.__version__ must be a string"
    assert version, "cmcourier.__version__ must be non-empty"
    assert re.match(
        r"^\d+\.\d+\.\d+(?:[-+].*)?$", version
    ), f"cmcourier.__version__ must be SemVer-compatible, got {version!r}"
