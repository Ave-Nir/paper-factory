"""
结构化日志 —— 方向7

设计原则：
- 输出 JSON 格式日志（便于 CI/CD 集成）
- 包含完整上下文：时间戳、阶段、错误码、位置、修复状态
- 支持多级别输出：DEBUG / INFO / WARN / ERROR
- 兼容原有 print 输出
"""
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# 日志级别映射
_LOG_LEVELS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARN": 30,
    "WARNING": 30,
    "ERROR": 40,
    "FATAL": 50,
}


class StructuredLogger:
    """
    结构化日志记录器。

    用法：
        logger = StructuredLogger("pipeline")
        logger.info("开始处理", paper="test.docx")
        logger.error("编译失败", error_code="PDF_GENERATION_FAILED", page=5)
    """

    def __init__(
        self,
        name: str,
        log_file: Optional[Path] = None,
        min_level: str = "INFO",
        pretty: bool = False,
    ) -> None:
        self.name = name
        self.log_file = log_file
        self.min_level = min_level
        self.min_level_value = _LOG_LEVELS.get(min_level, 20)
        self.pretty = pretty
        self._entries: List[Dict[str, Any]] = []

    def _log(self, level: str, message: str, **context: Any) -> None:
        """记录一条日志"""
        level_value = _LOG_LEVELS.get(level, 20)
        if level_value < self.min_level_value:
            return

        # JSON 序列化时安全降级：非基本类型转为字符串
        def _safe(obj: Any) -> Any:
            try:
                json.dumps(obj, ensure_ascii=False)
                return obj
            except (TypeError, ValueError):
                return repr(obj)

        safe_context = {k: _safe(v) for k, v in context.items()}

        entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "logger": self.name,
            "message": message,
            "context": safe_context,
        }

        self._entries.append(entry)

        # 控制台输出
        indent = "  " if not self.pretty else "  "
        level_str = f"[{level}]"
        ctx_str = ""
        if context:
            if self.pretty:
                try:
                    ctx_str = "\n" + json.dumps(safe_context, ensure_ascii=False, indent=2)
                except Exception:
                    ctx_str = " | " + str(safe_context)
            else:
                ctx_parts = [f"{k}={safe_context[k]}" for k in safe_context]
                ctx_str = " | " + ", ".join(ctx_parts)
        print(f"{indent}{level_str} {message}{ctx_str}", file=sys.stderr if level in ("ERROR", "FATAL") else sys.stdout)

        # 文件输出
        if self.log_file:
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                pass

    # 便捷方法
    def debug(self, message: str, **context: Any) -> None:
        self._log("DEBUG", message, **context)

    def info(self, message: str, **context: Any) -> None:
        self._log("INFO", message, **context)

    def warn(self, message: str, **context: Any) -> None:
        self._log("WARN", message, **context)

    def warning(self, message: str, **context: Any) -> None:
        self._log("WARNING", message, **context)

    def error(self, message: str, **context: Any) -> None:
        self._log("ERROR", message, **context)

    def fatal(self, message: str, **context: Any) -> None:
        self._log("FATAL", message, **context)

    def log_gate_result(
        self,
        gate_name: str,
        passed: bool,
        errors: List[str],
        warnings: List[str],
        issues: List[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        记录 Gate 检查结果（结构化，含 issues 位置信息）。
        """
        log_context = {
            "gate": gate_name,
            "passed": passed,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors,
            "warnings": warnings,
        }
        if issues:
            log_context["issues"] = issues
        if context:
            log_context.update(context)
        
        self._log(
            "INFO" if passed else "ERROR",
            f"Gate检查: {gate_name}",
            **log_context,
        )

    def log_fix_attempt(
        self,
        error_code: str,
        success: bool,
        strategy: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        记录自动修复尝试（方向10配合使用）。
        """
        self._log(
            "INFO" if success else "WARN",
            f"自动修复: {error_code}",
            error_code=error_code,
            success=success,
            strategy=strategy,
            details=details or {},
        )

    def get_entries(self) -> List[Dict[str, Any]]:
        """获取所有日志条目"""
        return self._entries.copy()

    def save_json(self, path: Path) -> None:
        """将所有日志保存为 JSON 文件"""
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "logger": self.name,
                        "entries": self._entries,
                        "summary": {
                            "total": len(self._entries),
                            "errors": sum(1 for e in self._entries if e["level"] in ("ERROR", "FATAL")),
                            "warnings": sum(1 for e in self._entries if e["level"] in ("WARN", "WARNING")),
                            "info": sum(1 for e in self._entries if e["level"] == "INFO"),
                        },
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception:
            pass


# 全局日志实例
_logger: Optional[StructuredLogger] = None


def get_logger() -> StructuredLogger:
    """获取全局日志实例"""
    global _logger
    if _logger is None:
        _logger = StructuredLogger("paper_pipeline")
    return _logger


def set_logger(logger: StructuredLogger) -> None:
    """设置全局日志实例"""
    global _logger
    _logger = logger
