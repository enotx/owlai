# backend/app/services/script_runner.py

"""Script 执行器 - 执行通用 Script（完全旁路 LLM）"""

import json
import os
import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Asset, Step
from app.services.sandbox import execute_code_in_sandbox
from app.config import UPLOADS_DIR

logger = logging.getLogger(__name__)


def _sse(data: dict) -> str:
    """生成 SSE 事件格式"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _step_to_dict(step: Step) -> dict:
    """Step ORM → 可序列化 dict"""
    return {
        "id": step.id,
        "task_id": step.task_id,
        "role": step.role,
        "step_type": step.step_type,
        "content": step.content,
        "code": step.code,
        "code_output": step.code_output,
        "created_at": step.created_at.isoformat() if step.created_at else None,
    }


async def run_script(
    task_id: str,
    asset: Asset,
    db: AsyncSession,
    env_vars_override: dict[str, str] | None = None,
    data_source_ids: list[str] | None = None,
) -> AsyncGenerator[str, None]:
    """
    执行通用 Script，完全旁路 LLM
    
    Args:
        task_id: Task ID
        asset: Script Asset
        db: 数据库会话
        env_vars_override: 用户覆盖的环境变量
        data_source_ids: 用户选择的 Knowledge/DuckDB table IDs
    
    Yields:
        SSE 格式的字符串
    """
    yield _sse({"type": "text", "content": f"🚀 Executing script: **{asset.name}**\n"})

    # 1. 读取 Asset 配置
    code = asset.code
    if not code:
        yield _sse({"type": "error", "content": "Script code is empty"})
        yield _sse({"type": "done"})
        return

    # 合并环境变量（用户覆盖 > Asset 默认）
    env_vars = json.loads(asset.env_vars_json) if asset.env_vars_json else {}
    if env_vars_override:
        env_vars.update(env_vars_override)

    allowed_modules = json.loads(asset.allowed_modules_json) if asset.allowed_modules_json else []

    # 2. 构建沙箱环境变量
    extra_envs = dict(env_vars)
    if allowed_modules:
        extra_envs["__allowed_modules__"] = json.dumps(allowed_modules)

    # 3. 构建 data_var_map — 从选中的 data sources 加载
    from app.services.data_processor import sanitize_variable_name
    from app.models import Knowledge
    from sqlalchemy import select

    data_var_map: dict[str, str] = {}

    if data_source_ids:
        for ds_id in data_source_ids:
            # 尝试作为 Knowledge 加载
            k = await db.get(Knowledge, ds_id)
            if k and k.type in ("csv", "excel") and k.file_path and os.path.exists(k.file_path):
                var_name = sanitize_variable_name(k.name)
                data_var_map[var_name] = os.path.abspath(k.file_path)
                continue
            
            # 尝试作为 DuckDB table（不加载为文件，代码中用 SQL 访问）
            # DuckDB tables 通过 WAREHOUSE_PATH env var 访问，无需预加载

    # 4. 发送 tool_start 事件
    yield _sse({
        "type": "tool_start",
        "code": code,
        "purpose": f"Script: {asset.name}",
    })

    # 5. 执行代码
    capture_dir = os.path.join(UPLOADS_DIR, task_id, "captures")
    os.makedirs(capture_dir, exist_ok=True)

    try:
        result = await execute_code_in_sandbox(
            code=code,
            data_var_map=data_var_map,
            capture_dir=capture_dir,
            injected_envs=extra_envs if extra_envs else None,
            timeout=600,  # Script 允许 10 分钟超时
        )
    except Exception as e:
        error_msg = f"Script execution error: {str(e)}"
        logger.error(error_msg)

        yield _sse({
            "type": "tool_result",
            "success": False,
            "output": None,
            "error": error_msg,
            "time": 0,
        })

        # 保存失败记录
        step = Step(
            task_id=task_id,
            role="assistant",
            step_type="tool_use",
            content=f"Script execution: {asset.name}",
            code=code,
            code_output=json.dumps({
                "success": False, "output": None,
                "error": error_msg, "execution_time": 0.0,
            }, ensure_ascii=False),
        )
        db.add(step)
        await db.commit()
        await db.refresh(step)

        yield _sse({"type": "step_saved", "step": _step_to_dict(step)})

        # 更新 Task 状态
        from app.models import Task
        from datetime import datetime
        task = await db.get(Task, task_id)
        if task:
            task.last_run_at = datetime.now()
            task.last_run_status = "failed"
            await db.commit()

        yield _sse({"type": "text", "content": f"\n❌ Script failed: {error_msg}"})
        yield _sse({"type": "done"})
        return

    # 6. 发送 tool_result 事件
    yield _sse({
        "type": "tool_result",
        "success": result["success"],
        "output": result.get("output"),
        "error": result.get("error"),
        "time": result.get("execution_time", 0),
        "dataframes": result.get("dataframes", []),
    })

    # 7. 处理沙箱内捕获的图表
    from app.tools import validate_echarts_option
    from app.tools.visualization import validate_map_config

    for chart_meta in result.get("charts", []):
        chart_option = chart_meta.get("option", {})
        ok, err = validate_echarts_option(chart_option)
        if ok:
            yield _sse({
                "type": "visualization",
                "title": chart_meta.get("title", "Untitled Chart"),
                "chart_type": chart_meta.get("chart_type", "bar"),
                "option": chart_option,
            })

    for map_meta in result.get("maps", []):
        map_config = map_meta.get("config", {})
        ok, err = validate_map_config(map_config)
        if ok:
            yield _sse({
                "type": "visualization",
                "title": map_meta.get("title", "Untitled Map"),
                "chart_type": "map",
                "option": map_config,
            })

    # 8. 保存执行结果为 Step
    step = Step(
        task_id=task_id,
        role="assistant",
        step_type="tool_use",
        content=f"Script execution: {asset.name}",
        code=code,
        code_output=json.dumps({
            "success": result["success"],
            "output": result.get("output"),
            "error": result.get("error"),
            "execution_time": result.get("execution_time", 0),
            "dataframes": result.get("dataframes", []),
        }, ensure_ascii=False),
    )
    db.add(step)
    await db.commit()
    await db.refresh(step)

    yield _sse({"type": "step_saved", "step": _step_to_dict(step)})

    # 9. 更新 Task 状态
    from app.models import Task
    from datetime import datetime
    task = await db.get(Task, task_id)
    if task:
        task.last_run_at = datetime.now()
        task.last_run_status = "success" if result["success"] else "failed"
        await db.commit()

    # 10. 总结
    if result["success"]:
        yield _sse({
            "type": "text",
            "content": f"\n✅ Script completed successfully in {result.get('execution_time', 0):.2f}s",
        })
    else:
        yield _sse({
            "type": "text",
            "content": f"\n❌ Script failed: {result.get('error', 'Unknown error')}",
        })

    yield _sse({"type": "done"})