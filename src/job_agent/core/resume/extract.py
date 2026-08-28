"""从 PDF / DOCX / 文本文件里抽出简历纯文本。

抽取只做「拿到文字」这一步，**不做整理**：把文字变成结构化的
``config/resume.md``（分段、保留全部数字、对齐市场词汇）需要读懂内容，
是 ``/job-init`` skill 的工作。代码硬要分段只会把信息弄丢。

依赖上的取舍：
  · PDF 用 pypdf——纯 Python、无编译依赖、体积小
  · DOCX 直接解压读 ``word/document.xml``。docx 本来就是个 zip，
    为了抽纯文本引入 python-docx（连带 lxml 这个需要编译的包）不值得
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from job_agent.errors import JobAgentError

#: WordprocessingML 命名空间
_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

TEXT_SUFFIXES = {".md", ".txt", ".markdown", ".text"}

_BLANK_RUN_RE = re.compile(r"\n{3,}")


class ResumeExtractError(JobAgentError):
    """简历文件读不出文字。"""

    exit_code = 5


def extract_text(path: Path) -> str:
    """按扩展名分派。返回的文本已折叠多余空行，未做任何结构化。"""
    if not path.is_file():
        raise ResumeExtractError(f"文件不存在：{path}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = _from_pdf(path)
    elif suffix == ".docx":
        text = _from_docx(path)
    elif suffix in TEXT_SUFFIXES:
        text = path.read_text(encoding="utf-8", errors="replace")
    elif suffix == ".doc":
        raise ResumeExtractError(
            f"不支持旧版 .doc 格式：{path}\n"
            "  用 Word / WPS / Pages 另存为 .docx 或导出 PDF 后再试。"
        )
    else:
        raise ResumeExtractError(
            f"不认识的简历格式「{suffix or '无扩展名'}」：{path}\n"
            "  支持 .pdf / .docx / .md / .txt。"
        )

    cleaned = _BLANK_RUN_RE.sub("\n\n", text.strip())
    if len(cleaned) < 50:
        raise ResumeExtractError(
            f"只从 {path.name} 里抽到 {len(cleaned)} 个字符，几乎肯定是失败了。\n"
            "  常见原因：PDF 是扫描件（图片），需要先 OCR；或文件本身是空的。"
        )
    return cleaned


def _from_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - 依赖已在 pyproject 里声明
        raise ResumeExtractError(
            "缺少 pypdf，无法读 PDF。跑 `uv sync` 安装依赖。"
        ) from exc

    try:
        reader = PdfReader(str(path))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        raise ResumeExtractError(f"PDF 解析失败（{path}）：{exc}") from exc


def _from_docx(path: Path) -> str:
    """读 ``word/document.xml``，按段落（``w:p``）换行、按制表符（``w:tab``）分隔。"""
    try:
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("word/document.xml")
    except KeyError as exc:
        raise ResumeExtractError(
            f"{path} 里没有 word/document.xml，可能不是有效的 .docx"
        ) from exc
    except (zipfile.BadZipFile, OSError) as exc:
        raise ResumeExtractError(f"DOCX 读取失败（{path}）：{exc}") from exc

    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise ResumeExtractError(f"DOCX 内容不是合法 XML（{path}）：{exc}") from exc

    lines: list[str] = []
    for paragraph in root.iter(f"{_W_NS}p"):
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{_W_NS}t":
                parts.append(node.text or "")
            elif node.tag == f"{_W_NS}tab":
                parts.append("\t")
            elif node.tag == f"{_W_NS}br":
                parts.append("\n")
        lines.append("".join(parts).strip())
    return "\n".join(lines)
