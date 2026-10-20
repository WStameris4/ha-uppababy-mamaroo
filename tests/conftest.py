"""Fixtures for the Mamaroo tests."""

from __future__ import annotations

from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> Generator[None]:
    """Load custom_components/ in every test."""
    yield
