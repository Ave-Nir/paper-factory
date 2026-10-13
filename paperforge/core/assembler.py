"""
LaTeX Assembler —— 将各章节 LaTeX 块拼接为完整 .tex 文件。

设计原则：
- 按模板定义的 section_order 顺序拼接
- 注入 preamble、标题页、参考文献
- 处理交叉引用和图表路径
"""

import os
from typing import Optional

from .types import LaTeXBlock, PaperSpec, ReferenceDB
from .template_engine import ResolvedTemplate


class LaTeXAssembler:
    """LaTeX 文档组装器"""
    
    def __init__(self, template: ResolvedTemplate):
        self.template = template
        self._sections: dict[str, str] = {}  # section_name → latex_content
        self._abstract: Optional[str] = None
    
    def add_section(self, block: LaTeXBlock) -> None:
        """添加一个章节的 LaTeX 内容"""
        if block.section_name == "abstract":
            self._abstract = block.content
        else:
            self._sections[block.section_name] = block.content
    
    def assemble(
        self,
        paper_spec: PaperSpec,
        ref_db: ReferenceDB,
        output_dir: str,
        filename: str = "paper",
    ) -> str:
        """组装完整 .tex 文件并写入磁盘。返回 .tex 文件路径。"""
        lines = []
        
        # 1. Preamble
        lines.append(self._render_preamble(paper_spec))
        
        # 2. Title page
        lines.append(self._render_title_page(paper_spec))
        
        # 3. Abstract (如果在 section_order 中)
        if "abstract" in self.template.section_order:
            if self._abstract:
                lines.append(self._abstract)
            else:
                lines.append("\\begin{abstract}\n\\end{abstract}")
        
        # 4. Sections (按 template 定义的顺序)
        for section_name in self.template.section_order:
            if section_name == "abstract":
                continue  # 已处理
            if section_name in self._sections:
                lines.append(self._sections[section_name])
            else:
                lines.append(f"% [WARNING] Missing section: {section_name}")
        
        # 5. Bibliography（仅当 section_order 中无 references 相关 section 时）
        has_refs_section = any(
            s in self.template.section_order for s in ("references", "references_cn")
        )
        if has_refs_section:
            # references section 会处理 bibliography 命令
            lines.append("\\end{document}")
        else:
            lines.append(f"\\bibliographystyle{{{self.template.bibliography_style}}}")
            lines.append("\\bibliography{references}")
            lines.append("\\end{document}")
        
        # 6. Write .tex file
        tex_content = "\n\n".join(lines)
        tex_path = os.path.join(output_dir, f"{filename}.tex")
        os.makedirs(output_dir, exist_ok=True)
        
        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex_content)
        
        # 7. Write .bib file
        bib_path = os.path.join(output_dir, "references.bib")
        with open(bib_path, "w", encoding="utf-8") as f:
            f.write(ref_db.export_bibtex())
        
        return tex_path
    
    def _render_preamble(self, paper_spec: PaperSpec) -> str:
        """生成 LaTeX preamble"""
        lines = []
        
        # 文档类
        cls_opts = ",".join(self.template.class_options)
        lines.append(f"\\documentclass[{cls_opts}]{{{self.template.document_class}}}")
        
        # 包
        for pkg in self.template.packages:
            if pkg.options:
                opts = ",".join(pkg.options)
                lines.append(f"\\usepackage[{opts}]{{{pkg.name}}}")
            else:
                lines.append(f"\\usepackage{{{pkg.name}}}")
        
        # 中文支持：若 language=chinese，自动注入 xeCJK + 字体配置
        if self.template.language == "chinese":
            lines.append("% === 中文支持 (xeCJK) ===")
            lines.append("\\usepackage{xeCJK}")
            lines.append("\\usepackage{fontspec}")
            lines.append("\\usepackage{amsmath,amssymb}")
            lines.append("\\usepackage{graphicx}")
            lines.append("\\usepackage{booktabs}")
            lines.append("\\usepackage{hyperref}")
            lines.append("\\usepackage{todonotes}")  # 支持 \todo 命令
            lines.append("% 中文字体设置（系统级宋体/黑体，如缺字体请安装 SimSun/SimHei/KaiTi）")
            lines.append("\\setCJKmainfont{SimSun}")
            lines.append("\\setCJKsansfont{SimHei}")
            lines.append("\\setCJKmonofont{SimSun}")
            lines.append("\\xeCJKsetup{CJKglue=\\hskip 0.1em plus 0.05em minus 0.05em}")
            lines.append("% 英文正文字体")
            lines.append("\\IfFontExistsTF{Times New Roman}{\\setmainfont{Times New Roman}}{}")
        
        # 额外 preamble
        if self.template.extra_preamble:
            lines.append(self.template.extra_preamble)
        
        # 标题/作者（非匿名模式）
        if not self.template.anonymous:
            title = paper_spec.get("title", "Untitled")
            lines.append(f"\\title{{{title}}}")
            
            authors = paper_spec.get("authors", [])
            author_str = " \\and ".join(
                f"{a['name']}\\\\ {a.get('affiliation', '')}"
                for a in authors
            )
            lines.append(f"\\author{{{author_str}}}")
        
        # 引用样式（仅当无 references section 时）
        has_refs_section = any(
            s in self.template.section_order for s in ("references", "references_cn")
        )
        if not has_refs_section:
            lines.append(f"\\bibliographystyle{{{self.template.bibliography_style}}}")
        
        lines.append("\\begin{document}")
        return "\n".join(lines)
    
    def _render_title_page(self, paper_spec: PaperSpec) -> str:
        """生成标题页"""
        lines = []
        
        if not self.template.anonymous:
            title = paper_spec.get("title", "Untitled")
            lines.append(f"\\title{{{title}}}")
            lines.append("\\maketitle")
        else:
            # 匿名模式：使用 venue 自带的标题处理
            lines.append("\\maketitle")
        
        return "\n".join(lines)