"""帮助文本工具：把 TOML 段名转义成字面量。

typer 用 rich 渲染 ``--help``，而 rich 会把 ``[...]`` 当成标记语言吃掉。
这个 CLI 的帮助文本里全是 ``[agent.providers.*]`` 这类 TOML 段名，
不转义的话「默认取 [profiles].default」会显示成「默认取 .default」——
不报错、不留痕，只是安静地少了半句话。

所以**帮助文本里出现方括号时一律套一层** :func:`h`。
``tests/test_boundaries.py::test_help_text_escapes_toml_sections`` 会扫描
``cli/`` 强制这条，免得下一个人（或下一次的我）又踩一遍。
"""

from __future__ import annotations

from rich.markup import escape as h

__all__ = ["h"]
