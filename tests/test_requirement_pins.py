"""The holidays pin has to say the same thing in all three places.

Home Assistant installs what manifest.json asks for; the test suite installs
what pyproject.toml asks for.  Nothing ties the two together, so a version bump
applied to one of them alone would leave the suite exercising a release that no
installation ever runs — and test_zone_schedule.py would then be pinning the
Christmas Eve rule against the wrong package.
"""
from __future__ import annotations

import json
import tomllib
from importlib.metadata import version
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "custom_components" / "enea_prices" / "manifest.json"
PYPROJECT = REPO / "pyproject.toml"

PACKAGE = "holidays"
MINIMUM = (0, 64)
"""Christmas Eve became a statutory holiday in 2025; earlier releases omit it."""


def _pinned_in(requirements: list[str]) -> str:
    """Return the version PACKAGE is pinned to in a list of requirements."""
    pins = [
        req.removeprefix(f"{PACKAGE}==")
        for req in requirements
        if req.startswith(f"{PACKAGE}==")
    ]

    assert len(pins) == 1, f"expected exactly one {PACKAGE}== pin, got {requirements}"
    return pins[0]


@pytest.fixture
def manifest_pin() -> str:
    """The version Home Assistant would install for a real user."""
    return _pinned_in(json.loads(MANIFEST.read_text(encoding="utf-8"))["requirements"])


def test_pyproject_pins_what_the_manifest_asks_for(manifest_pin: str) -> None:
    """The dev group has to name the same version as the manifest."""
    dev = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["dependency-groups"]["dev"]

    assert _pinned_in(dev) == manifest_pin


def test_the_suite_runs_against_the_pinned_version(manifest_pin: str) -> None:
    """The installed package has to be the pinned one, not whatever resolved."""
    assert version(PACKAGE) == manifest_pin


def test_the_pin_is_new_enough_to_know_christmas_eve(manifest_pin: str) -> None:
    """A downgrade below the lower bound would silently unpin a billing rule.

    Christmas Eve falling on a working day is billed off-peak in G12w only
    because the holidays package reports it as statutory, which it does from
    0.64 onwards.  Below that the day would quietly be billed at the peak rate.
    """
    parts = tuple(int(piece) for piece in manifest_pin.split(".")[: len(MINIMUM)])

    assert parts >= MINIMUM
