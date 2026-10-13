#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
论文处理完整流程 —— 入口脚本

使用方法:
  $env:LLM_API_KEY="sk-..."
  $env:IMAGE_API_KEY="sk-..."
  python run.py <论文.docx>
"""
import sys
from pathlib import Path

# 将 src 加入路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from paper_pipeline.cli import main

if __name__ == "__main__":
    sys.exit(main())
