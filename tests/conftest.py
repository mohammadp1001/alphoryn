"""Shared pytest fixtures for all unit and integration tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def redirect_reports_dir(tmp_path, monkeypatch):
    """Redirect config.REPORTS_DIR to a per-test temp directory.

    Prevents tests from writing into the project-level reports/ directory and
    ensures each test gets a clean, isolated output space that is cleaned up
    automatically after the test.
    """
    import config

    monkeypatch.setattr(config, "REPORTS_DIR", tmp_path / "reports")
