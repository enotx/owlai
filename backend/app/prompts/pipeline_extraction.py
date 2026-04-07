# backend/app/prompts/pipeline_extraction.py

"""
Pipeline 提取相关的 LLM Prompt 模板。

核心原则：
- transform_code 必须是确定性的纯 Python 脚本
- LLM 仅在提取阶段参与，产出物是静态代码文本
- Pipeline 执行时零 LLM 调用
"""

PIPELINE_EXTRACTION_SYSTEM = """\
You are a **Data Pipeline Extractor**. Your job is to analyze a task's code execution history \
and produce a clean, reproducible, self-contained Python pipeline script.

## Rules — STRICTLY FOLLOW
1. Combine all related code blocks into a **single self-contained script**.
2. **Remove** all debugging, exploration, print(), display() calls — keep only the core transform logic.
3. Remove any code that was part of failed attempts or exploratory dead-ends.
4. The script MUST produce a single pandas DataFrame named `df_output` as its final result.
5. The script can use: pandas, numpy, duckdb, re, json, datetime, math, statistics, collections.
6. If the original code fetched data from an API, the pipeline MUST reproduce that fetch. \
   Include the exact API call so the pipeline is re-runnable.
7. If the original code loaded uploaded CSVs, reference them via their original variable names \
   (they will be pre-loaded in the sandbox).
8. Do NOT use any LLM calls, AI inference, or non-deterministic operations.
9. Keep column names, data types, and transformations exactly as they appeared in the successful execution.
10. Add brief inline comments explaining each major step.

## Output Format
Return ONLY a JSON object (no markdown fences, no extra text):
{
  "table_name": "snake_case_name",
  "display_name": "Human Readable Name",
  "description": "1-2 sentence description of what this table contains",
  "source_type": "csv_upload" | "api" | "datasource" | "manual",
  "source_config": {},
  "transform_code": "import pandas as pd\\n...",
  "transform_description": "Step-by-step: 1. Load data... 2. Clean... 3. Aggregate..."
}
"""


def build_pipeline_extraction_prompt(
    code_history: list[dict],
    user_instructions: str,
    knowledge_context: str = "",
) -> str:
    """
    构建 pipeline 提取的 user prompt。

    Args:
        code_history: 成功执行的代码历史
            [{"code": str, "output": str, "purpose": str}, ...]
        user_instructions: 用户的附加指令（/derive 后面的文本）
        knowledge_context: 当前 Task 的 Knowledge 上下文（数据源信息）
    """
    # 构建代码历史部分
    history_parts = []
    for i, entry in enumerate(code_history, 1):
        part = f"### Step {i}: {entry.get('purpose', 'Code execution')}\n"
        part += f"```python\n{entry['code']}\n```\n"
        output = entry.get("output", "")
        if output:
            # 截断过长的输出
            if len(output) > 2000:
                output = output[:2000] + "\n... [truncated]"
            part += f"**Output:**\n```\n{output}\n```\n"
        history_parts.append(part)

    code_history_text = "\n".join(history_parts)

    prompt = f"""## Task Code Execution History (successful steps only)

{code_history_text}

## Available Data Sources
{knowledge_context or "[No additional data sources]"}

## User Instructions
{user_instructions or "Save the final analysis result as a reusable data source."}

Based on the above, extract a clean pipeline. Remember:
- The script must produce `df_output` as the final DataFrame.
- Remove all exploration/debugging code.
- Keep the script deterministic and re-runnable.
"""
    return prompt