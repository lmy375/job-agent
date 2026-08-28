"""简历文本抽取。不碰真实简历文件，DOCX / PDF 都在测试里现造。"""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from job_agent.core.resume import ResumeExtractError, extract_text

LONG_TEXT = "梁某某 · 8 年经验 · 负责 Agent 平台建设，带 5 人团队，支撑峰值 10000 BTC 资产规模。" * 2

_DOCX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
 <w:body>
  <w:p><w:r><w:t>{first}</w:t></w:r></w:p>
  <w:p><w:r><w:t>第二段</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t>制表符后</w:t></w:r></w:p>
 </w:body>
</w:document>
"""


def make_docx(path: Path, first: str = LONG_TEXT) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", _DOCX_XML.format(first=first))
    return path


def test_extract_txt(tmp_path):
    path = tmp_path / "resume.md"
    path.write_text(f"# 简历\n\n{LONG_TEXT}\n", encoding="utf-8")
    assert "Agent 平台建设" in extract_text(path)


def test_extract_docx_keeps_paragraphs_and_tabs(tmp_path):
    text = extract_text(make_docx(tmp_path / "resume.docx"))
    assert LONG_TEXT in text
    assert "第二段\t制表符后" in text


def test_extract_docx_preserves_numbers(tmp_path):
    """数字是简历里最值钱的部分，抽取不能把它们丢掉。"""
    text = extract_text(make_docx(tmp_path / "r.docx"))
    for number in ("8 年", "5 人", "10000 BTC"):
        assert number in text


def test_missing_file(tmp_path):
    with pytest.raises(ResumeExtractError, match="文件不存在"):
        extract_text(tmp_path / "nope.pdf")


def test_legacy_doc_rejected_with_actionable_message(tmp_path):
    path = tmp_path / "resume.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0old word")
    with pytest.raises(ResumeExtractError, match=r"另存为 \.docx"):
        extract_text(path)


def test_unknown_suffix(tmp_path):
    path = tmp_path / "resume.pages"
    path.write_text("x" * 200, encoding="utf-8")
    with pytest.raises(ResumeExtractError, match="不认识的简历格式"):
        extract_text(path)


def test_too_short_text_is_treated_as_failure(tmp_path):
    """扫描件 PDF 抽出来是空的。静默返回空串会让 skill 以为简历没内容。"""
    path = tmp_path / "resume.txt"
    path.write_text("短", encoding="utf-8")
    with pytest.raises(ResumeExtractError, match="几乎肯定是失败了"):
        extract_text(path)


def test_broken_docx(tmp_path):
    path = tmp_path / "resume.docx"
    path.write_bytes(b"not a zip")
    with pytest.raises(ResumeExtractError, match="DOCX 读取失败"):
        extract_text(path)


def test_docx_without_document_xml(tmp_path):
    path = tmp_path / "resume.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("other.xml", "<a/>")
    with pytest.raises(ResumeExtractError, match=r"没有 word/document\.xml"):
        extract_text(path)
