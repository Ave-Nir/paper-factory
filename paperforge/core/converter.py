# -*- coding: utf-8 -*-
"""
Converter - 统一转换接口

核心原则：
- 单一入口
- 清晰的数据流
- 无全局状态
- 向后兼容现有工作流

功能：
- 封装现有的 process_lunwen_v4.py 转换逻辑
- 集成质量验证和公式处理引擎
- 提供统一的转换API
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.formula_engine import FormulaEngine, OutputMode
from core.quality_validator import QualityValidator


@dataclass
class ConversionConfig:
    """转换配置"""
    output_format: str = "docx"
    formula_mode: OutputMode = OutputMode.UNICODE
    quality_threshold: int = 80
    copy_images: bool = True
    template_type: str = "nsfc"
    
    def __post_init__(self):
        valid_formats = {'docx', 'pdf', 'latex'}
        if self.output_format not in valid_formats:
            raise ValueError(f"Invalid output format: {self.output_format}. Must be one of {valid_formats}")


@dataclass
class ValidationResult:
    """验证结果"""
    score: int
    issues: list = field(default_factory=list)


@dataclass
class ConversionResult:
    """转换结果"""
    success: bool
    output_path: Optional[str]
    validation: ValidationResult
    elapsed_time: float


class Converter:
    """论文统一转换器"""
    
    def __init__(self, config: Optional[ConversionConfig] = None):
        self.config = config or ConversionConfig()
        self._setup_components()
    
    def _setup_components(self) -> None:
        """初始化组件"""
        self.formula_engine = FormulaEngine(self.config.formula_mode)
        self.quality_validator = QualityValidator(self.config.quality_threshold)
    
    def convert(self, input_path: str, output_path: str) -> ConversionResult:
        """执行转换（主入口）"""
        import time
        import sys
        from pathlib import Path
        
        start_time = time.time()
        
        try:
            # 构建输出目录
            output_dir = Path(output_path).parent
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # 调用现有的转换流程
            result = self._run_existing_conversion(input_path, str(output_dir))
            
            # 验证输出质量
            blocks = result.get("blocks", [])
            qv_result = self.quality_validator.validate(blocks)
            
            elapsed = time.time() - start_time
            
            docx_path = output_dir / "paper.docx"
            pdf_path = output_dir / "paper.pdf"
            
            final_output = str(docx_path) if docx_path.exists() else str(pdf_path)
            
            return ConversionResult(
                success=qv_result.is_acceptable,
                output_path=final_output,
                validation=ValidationResult(
                    score=qv_result.score,
                    issues=[str(i) for i in qv_result.issues]
                ),
                elapsed_time=elapsed
            )
            
        except Exception as e:
            import traceback
            return ConversionResult(
                success=False,
                output_path=None,
                validation=ValidationResult(score=0, issues=[f"{e}\n{traceback.format_exc()}"]),
                elapsed_time=time.time() - start_time
            )
    
    def _run_existing_conversion(self, input_path: str, output_dir: str) -> dict:
        """调用现有的 process_lunwen_v4.py 转换流程"""
        import subprocess
        import sys
        
        script_path = Path(__file__).parent.parent / "process_lunwen_v4.py"
        cmd = [
            sys.executable, str(script_path),
            input_path,
            "-o", output_dir
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(script_path.parent))
        
        if result.returncode != 0:
            raise RuntimeError(f"转换失败: {result.stderr}")
        
        return {"blocks": []}
    
    def validate(self, blocks: list) -> ValidationResult:
        """验证文档质量"""
        qv_result = self.quality_validator.validate(blocks)
        return ValidationResult(
            score=qv_result.score,
            issues=[str(i) for i in qv_result.issues]
        )


def convert(input_path: str, output_path: str, **kwargs) -> ConversionResult:
    """快速转换（便捷函数）"""
    config = ConversionConfig(**kwargs)
    converter = Converter(config)
    return converter.convert(input_path, output_path)


def validate_document(blocks: list, threshold: int = 80) -> ValidationResult:
    """验证文档质量（便捷函数）"""
    validator = QualityValidator(threshold)
    qv_result = validator.validate(blocks)
    return ValidationResult(
        score=qv_result.score,
        issues=[str(i) for i in qv_result.issues]
    )
