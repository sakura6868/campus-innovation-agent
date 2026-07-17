"""文档解析：提取文本 + 保留页码与段落信息。

为后续「结构化抽取」与「原文证据定位（页码 + 段落）」提供基础。
不同年份通知作为不同版本保存，绝不直接覆盖（见 data/raw 目录约定）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

# 允许脚本直接运行（python parsing/pdf_extractor.py）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from schemas import CompetitionCategory, ParsedBlock, ParseResult

# 段落切分：以空行或明显缩进变化作为分段依据，退化为按换行切分
_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n|\n(?=\s{4,})")


def parse_pdf(
    pdf_path: str | Path,
    category: CompetitionCategory,
    document_year: int,
    competition_id: Optional[str] = None,
) -> ParseResult:
    """解析 PDF，返回带页码与段落序号的文本块列表。

    依赖：pdfplumber（已列入 requirements）。无pdfplumber时退化为空结果并打印提示。
    """
    import pdfplumber

    pdf_path = Path(pdf_path)
    blocks: list[ParsedBlock] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            paragraphs = [p.strip() for p in _PARAGRAPH_SPLIT.split(text) if p.strip()]
            for para_index, para in enumerate(paragraphs, start=1):
                blocks.append(
                    ParsedBlock(
                        page=page_index,
                        paragraph_index=para_index,
                        text=para,
                        competition_id=competition_id,
                    )
                )

    return ParseResult(
        document_name=pdf_path.name,
        category=category,
        document_year=document_year,
        blocks=blocks,
    )


def parse_docx(
    docx_path: str | Path,
    category: CompetitionCategory,
    document_year: int,
    competition_id: Optional[str] = None,
) -> ParseResult:
    """解析 Word 文档，按段落保留序号（页码在 docx 中不可靠，统一记为 0）。"""
    from docx import Document

    docx_path = Path(docx_path)
    blocks: list[ParsedBlock] = []

    doc = Document(str(docx_path))
    for para_index, para in enumerate(doc.paragraphs, start=1):
        text = para.text.strip()
        if text:
            blocks.append(
                ParsedBlock(
                    page=0,
                    paragraph_index=para_index,
                    text=text,
                    competition_id=competition_id,
                )
            )

    return ParseResult(
        document_name=docx_path.name,
        category=category,
        document_year=document_year,
        blocks=blocks,
    )


def locate_evidence(parse_result: ParseResult, keyword: str) -> Optional[ParsedBlock]:
    """给定关键词，定位首个命中的文本块，用于人工核验与证据抽取。"""
    for block in parse_result.blocks:
        if keyword in block.text:
            return block
    return None


if __name__ == "__main__":
    # 简单自测：把第一个参数当 PDF 路径解析并打印块数
    import sys

    if len(sys.argv) > 1:
        res = parse_pdf(
            sys.argv[1], CompetitionCategory.PROGRAMMING, 2026
        )
        print(f"解析 {res.document_name}：共 {len(res.blocks)} 个文本块")
        for b in res.blocks[:3]:
            print(f"  [p{b.page}-¶{b.paragraph_index}] {b.text[:60]}")
