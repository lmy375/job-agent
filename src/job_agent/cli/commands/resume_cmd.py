"""``job resume``：把已有简历文件转成文本，供 skill 整理进 profile 的 ``resume.md``。

刻意**不自动覆盖** ``resume.md``：抽出来的是一堆没有结构的文字，
直接写进去会得到一份排版稀烂、还可能丢掉数字的简历。
默认打到 stdout，由 ``/job-init`` skill 接手整理——它会保留全部事实与数字、
对齐市场词汇、缺信息时留 `<待补>`。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from job_agent.cli.state import CliState, echo_ok, echo_warn
from job_agent.core.resume import extract_text

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("import", help="从 PDF / DOCX / TXT 简历里抽出纯文本。")
def import_resume(
    ctx: typer.Context,
    source: Annotated[Path, typer.Argument(help="简历文件路径（.pdf / .docx / .md / .txt）。")],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="写到文件；不给则打到标准输出。"),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="--output 指向的文件已存在时也覆盖。")
    ] = False,
) -> None:
    state: CliState = ctx.obj
    text = extract_text(source.expanduser())

    if output is None:
        typer.echo(text)
        # 提示打到 stderr，这样 `job resume import x.pdf > out.txt` 不会把它混进正文
        typer.secho(
            f"\n（以上是 {source.name} 的纯文本，{len(text)} 字符。"
            "下一步让 Claude 跑 /job-init 整理成 profile 里的 resume.md——"
            "它会保留全部数字、对齐市场词汇，缺信息时留 <待补>。）",
            fg=typer.colors.BRIGHT_BLACK,
            err=True,
        )
        return

    target = output.expanduser()
    if target.exists() and not force:
        echo_warn(f"{target} 已存在，未改动（加 --force 覆盖）")
        raise typer.Exit(code=1)

    settings = state.context().settings
    if target.resolve() == settings.profile.resume.resolve() and not force:
        echo_warn(
            f"不建议直接写 {target}：抽出来的是无结构文本，"
            "会覆盖掉整理好的简历。确实要这么做请加 --force。"
        )
        raise typer.Exit(code=1)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    echo_ok(f"已写入 {target}（{len(text)} 字符）")
