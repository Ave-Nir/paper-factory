"""
conftest.py — paper_pipeline pytest fixtures

Provides shared test fixtures and path setup. Critical for ensuring tests
run correctly regardless of cwd or absolute path assumptions.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


# Ensure the paper_pipeline source tree is importable. We add src/ to sys.path
# so tests can import paper_pipeline.* without installation.
_PIPELINE_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _PIPELINE_ROOT / "src"

if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))


@pytest.fixture(autouse=True)
def _clean_pipeline_env(monkeypatch):
    """
    Ensure each test runs without leaking API keys into the environment.

    Tests that exercise get_settings() must explicitly set required env vars
    via monkeypatch.setenv() within the test body. If a test does not set
    LLM_API_KEY / IMAGE_API_KEY, get_settings() will raise
    ConfigurationError (fail-closed).
    """
    for var in (
        "LLM_API_KEY",
        "IMAGE_API_KEY",
        "PAPER_PIPELINE_HOME",
        "PAPER2DIAGRAM_HOME",
        "PAPERFORGE_HOME",
        "MIKTEX_BIN",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def work_dir(tmp_path):
    """Provide a temporary work directory for typeable / process output."""
    return tmp_path


@pytest.fixture
def small_tex(tmp_path):
    """A minimal valid .tex fixture for TypesetGate / pipeline tests."""
    tex_path = tmp_path / "paper.tex"
    tex_path.write_text(
        r"""
\documentclass{article}
\begin{document}
\section{Introduction}
Hello world.
\end{document}
""",
        encoding="utf-8",
    )
    return tex_path


@pytest.fixture
def empty_file(tmp_path):
    """A 0-byte file for input validation tests."""
    p = tmp_path / "empty.docx"
    p.write_bytes(b"")
    return p


@pytest.fixture
def tiny_file(tmp_path):
    """A sub-1KB file for input validation tests."""
    p = tmp_path / "tiny.md"
    p.write_text("# tiny\n", encoding="utf-8")
    return p


@pytest.fixture
def unsupported_file(tmp_path):
    """An unsupported file extension."""
    p = tmp_path / "bad.xyz"
    p.write_text("ignored", encoding="utf-8")
    return p


@pytest.fixture
def supported_docx(tmp_path):
    """A valid-extension file (>1KB) for InputGate happy-path."""
    p = tmp_path / "paper.docx"
    p.write_bytes(b"PK\x03\x04" + b"\x00" * 2000)
    return p
