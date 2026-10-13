"""
test_exceptions.py — 异常体系测试

确保所有异常携带 stage/context/cause，并且错误信息可读可追溯。
"""
from __future__ import annotations

import pytest

from paper_pipeline.exceptions import (
    ConfigurationError,
    DiagramGenerationError,
    InsertionError,
    LLMError,
    PipelineError,
    TypesetError,
    ValidationError,
)


class TestPipelineErrorBase:
    """PipelineError 基类必须支持 stage/context/cause 三段信息."""

    def test_minimal_construction(self):
        e = PipelineError("boom")
        assert "boom" in str(e)
        assert e.stage is None
        assert e.context == {}
        assert e.cause is None

    def test_with_stage(self):
        e = PipelineError("bad config", stage="CONFIG")
        assert "[CONFIG]" in str(e)
        assert "bad config" in str(e)

    def test_with_context(self):
        e = PipelineError("x", stage="X", context={"key": "value"})
        assert "key=value" in str(e)

    def test_with_cause(self):
        inner = ValueError("inner reason")
        e = PipelineError("outer", cause=inner)
        assert "ValueError" in str(e)
        assert "inner reason" in str(e)

    def test_full_chain(self):
        inner = KeyError("missing")
        e = PipelineError(
            "outer message",
            stage="VERIFY",
            context={"file": "x.pdf", "page": 3},
            cause=inner,
        )
        s = str(e)
        assert "[VERIFY]" in s
        assert "outer message" in s
        assert "file=x.pdf" in s
        assert "page=3" in s
        assert "KeyError" in s


class TestExceptionHierarchy:
    """所有子类必须继承自 PipelineError 且能正确构造."""

    @pytest.mark.parametrize("cls", [
        ConfigurationError,
        ValidationError,
        DiagramGenerationError,
        TypesetError,
        InsertionError,
        LLMError,
    ])
    def test_subclass_is_pipeline_error(self, cls):
        e = cls("test", stage="X", context={"k": 1})
        assert isinstance(e, PipelineError)
        assert isinstance(e, Exception)

    def test_configuration_error_message(self):
        e = ConfigurationError("missing LLM_API_KEY", context={"env_var": "LLM_API_KEY"})
        assert "LLM_API_KEY" in str(e)
