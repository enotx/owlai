# backend/app/services/export_service.py
"""对话导出服务：支持 Markdown 和 Jupyter Notebook (.ipynb) 格式"""

import json
from datetime import datetime

from app.models import Task, Step, Knowledge


async def export_as_markdown(
    task: Task,
    steps: list[Step],
    knowledge_items: list[Knowledge],
) -> str:
    """将对话导出为 Markdown 格式"""
    lines: list[str] = []

    # ── 标题 & 元信息 ──
    lines.append(f"# {task.title}")
    lines.append("")
    lines.append(
        f"> Exported from Owl · {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    lines.append("")

    # ── Knowledge 概况 ──
    if knowledge_items:
        lines.append("---")
        lines.append("")
        lines.append("## Knowledge")
        lines.append("")
        lines.append("| Name | Type | Details |")
        lines.append("|------|------|---------|")
        for k in knowledge_items:
            detail = _knowledge_detail(k)
            lines.append(f"| {k.name} | {k.type} | {detail} |")
        lines.append("")

    # ── 对话记录 ──
    lines.append("---")
    lines.append("")
    lines.append("## Conversation")
    lines.append("")

    for step in steps:
        if step.step_type == "user_message":
            lines.append("**👤 User:**")
            lines.append("")
            lines.append(step.content)
            lines.append("")
            lines.append("---")
            lines.append("")

        elif step.step_type == "assistant_message":
            lines.append("**🤖 Assistant:**")
            lines.append("")
            lines.append(step.content)
            lines.append("")
            lines.append("---")
            lines.append("")

        elif step.step_type == "tool_use":
            _render_tool_use_md(lines, step)

        elif step.step_type == "visualization":
            _render_visualization_md(lines, step)

    return "\n".join(lines)


async def export_as_notebook(
    task: Task,
    steps: list[Step],
    knowledge_items: list[Knowledge],
) -> dict:
    """将对话导出为 Jupyter Notebook (ipynb) 格式"""
    cells: list[dict] = []

    # ── 标题 cell ──
    header_lines = [
        f"# {task.title}\n",
        "\n",
        f"> Exported from Owl · {datetime.now().strftime('%Y-%m-%d %H:%M')}\n",
    ]
    if knowledge_items:
        header_lines.append("\n")
        header_lines.append("### Knowledge\n")
        header_lines.append("\n")
        header_lines.append("| Name | Type | Details |\n")
        header_lines.append("|------|------|---------|  \n")
        for k in knowledge_items:
            detail = _knowledge_detail(k)
            header_lines.append(f"| {k.name} | {k.type} | {detail} |\n")
    cells.append(_md_cell(header_lines))

    # ── 对话 cells ──
    exec_count = 1
    for step in steps:
        if step.step_type == "user_message":
            cells.append(
                _md_cell([
                    "**👤 User:**\n",
                    "\n",
                    f"{step.content}\n",
                ])
            )

        elif step.step_type == "assistant_message":
            cells.append(
                _md_cell([
                    "**🤖 Assistant:**\n",
                    "\n",
                    f"{step.content}\n",
                ])
            )

        elif step.step_type == "tool_use":
            cell, exec_count = _build_tool_use_cell(step, exec_count)
            cells.append(cell)

        elif step.step_type == "visualization":
            cell, exec_count = _build_visualization_cell(step, exec_count)
            cells.append(cell)

    notebook = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
                "version": "3.12.0",
                "mimetype": "text/x-python",
                "file_extension": ".py",
            },
        },
        "cells": cells,
    }
    return notebook


# ───────────── 内部工具函数 ─────────────


def _knowledge_detail(k: Knowledge) -> str:
    """从 Knowledge.metadata_json 中提取摘要信息"""
    if not k.metadata_json:
        return ""
    try:
        meta = json.loads(k.metadata_json)
        if "row_count" in meta and "columns" in meta:
            return f"{meta['row_count']} rows × {len(meta['columns'])} columns"
        if "sheets" in meta:
            return f"{len(meta['sheets'])} sheet(s)"
    except Exception:
        pass
    return ""


def _render_tool_use_md(lines: list[str], step: Step) -> None:
    """渲染 tool_use Step 为 Markdown"""
    purpose = step.content or "Code execution"
    lines.append(f"**💻 Code Execution** — {purpose}")
    lines.append("")

    if step.code:
        lines.append("```python")
        lines.append(step.code)
        lines.append("```")
        lines.append("")

    if step.code_output:
        try:
            result = json.loads(step.code_output)
            status = "✅ Succeeded" if result.get("success") else "❌ Failed"
            exec_time = result.get("execution_time", 0)
            lines.append(f"> {status} ({exec_time:.2f}s)")
            lines.append(">")

            if result.get("output"):
                lines.append("> ```")
                for line in result["output"].split("\n"):
                    lines.append(f"> {line}")
                lines.append("> ```")

            if result.get("error"):
                lines.append("> ```")
                for line in result["error"].split("\n"):
                    lines.append(f"> {line}")
                lines.append("> ```")

            if result.get("dataframes"):
                for df in result["dataframes"]:
                    cols = len(df.get("columns", []))
                    rows = df.get("row_count", 0)
                    lines.append(
                        f"> 📊 `{df['name']}` ({rows} rows × {cols} cols)"
                    )
        except Exception:
            lines.append(f"> Output: {step.code_output[:500]}")

    lines.append("")
    lines.append("---")
    lines.append("")


def _render_visualization_md(lines: list[str], step: Step) -> None:
    """渲染 visualization Step 为 Markdown"""
    lines.append("**📊 Visualization**")
    lines.append("")
    if step.code_output:
        try:
            viz = json.loads(step.code_output)
            title = viz.get("title", step.content)
            chart_type = viz.get("chart_type", "unknown")
            lines.append(f"**{title}** (Chart type: {chart_type})")
            lines.append("")
            lines.append("<details><summary>ECharts Option JSON</summary>")
            lines.append("")
            lines.append("```json")
            lines.append(
                json.dumps(viz.get("option", {}), indent=2, ensure_ascii=False)
            )
            lines.append("```")
            lines.append("")
            lines.append("</details>")
        except Exception:
            lines.append(step.content)
    else:
        lines.append(step.content)
    lines.append("")
    lines.append("---")
    lines.append("")


def _build_tool_use_cell(
    step: Step, exec_count: int
) -> tuple[dict, int]:
    """构建 tool_use Step 对应的 Code Cell"""
    purpose = step.content or "Code execution"
    source_lines: list[str] = [f"# {purpose}\n"]

    if step.code:
        for line in step.code.split("\n"):
            source_lines.append(f"{line}\n")

    outputs: list[dict] = []
    if step.code_output:
        try:
            result = json.loads(step.code_output)
            text_parts: list[str] = []
            if result.get("output"):
                text_parts.append(result["output"])
            if result.get("error"):
                text_parts.append(result["error"])
            if result.get("dataframes"):
                for df in result["dataframes"]:
                    cols = len(df.get("columns", []))
                    rows = df.get("row_count", 0)
                    text_parts.append(
                        f"[DataFrame: {df['name']} ({rows} rows × {cols} cols)]"
                    )
            output_text = "\n".join(text_parts)
            if output_text.strip():
                stream_name = "stdout" if result.get("success") else "stderr"
                outputs.append({
                    "output_type": "stream",
                    "name": stream_name,
                    "text": [ln + "\n" for ln in output_text.split("\n")],
                })
        except Exception:
            outputs.append({
                "output_type": "stream",
                "name": "stdout",
                "text": [step.code_output + "\n"],
            })

    cell = _code_cell(source_lines, outputs, exec_count)
    return cell, exec_count + 1


def _build_visualization_cell(
    step: Step, exec_count: int
) -> tuple[dict, int]:
    """构建 visualization Step 对应的 Code Cell（以 Python dict 形式展示 ECharts option）"""
    source_lines: list[str] = []
    if step.code_output:
        try:
            viz = json.loads(step.code_output)
            title = viz.get("title", step.content)
            chart_type = viz.get("chart_type", "unknown")
            source_lines.append(f"# 📊 Visualization: {title}\n")
            source_lines.append(f"# Chart type: {chart_type}\n")
            source_lines.append("\n")
            source_lines.append("# ECharts option (rendered interactively in Owl)\n")
            option_str = json.dumps(
                viz.get("option", {}), indent=2, ensure_ascii=False
            )
            source_lines.append(f"option = {option_str}\n")
        except Exception:
            source_lines.append(f"# Visualization: {step.content}\n")
    else:
        source_lines.append(f"# Visualization: {step.content}\n")

    cell = _code_cell(source_lines, [], exec_count)
    return cell, exec_count + 1


def _md_cell(source: list[str]) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source}


def _code_cell(
    source: list[str],
    outputs: list[dict],
    execution_count: int | None = None,
) -> dict:
    return {
        "cell_type": "code",
        "metadata": {},
        "source": source,
        "outputs": outputs,
        "execution_count": execution_count,
    }