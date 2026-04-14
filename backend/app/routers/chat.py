# backend/app/routers/chat.py

"""Chat 对话 API —— ReAct Agent + SSE 流式回复"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Step, Visualization
from app.schemas import ChatRequest, StepResponse
from app.services.agent import run_agent_stream
import asyncio
import os
import json as _json


from app.config import UPLOADS_DIR


router = APIRouter(prefix="/api/chat", tags=["chat"])


# ── SSE 流式对话（ReAct Agent） ────────────────────────────────
@router.post("/stream")
async def stream_message(body: ChatRequest, db: AsyncSession = Depends(get_db)):
    """
    通过 SSE 逐步推送 Agent 的分析过程。
    支持mode参数切换执行模式，支持model_override显式指定模型。
    """
    mode = getattr(body, 'mode', None)
    
    # 解析用户显式指定的模型
    model_override = None
    if hasattr(body, 'model_override') and body.model_override:
        model_override = (
            body.model_override.provider_id,
            body.model_override.model_id,
        )
    
    async def event_generator():
        try:
            async for sse_line in run_agent_stream(
                task_id=body.task_id,
                user_message=body.message,
                db=db,
                mode=mode,
                model_override=model_override,  # 传递用户指定
            ):
                yield sse_line
        except asyncio.CancelledError:
            return
        except Exception as e:
            import json
            yield f"data: {json.dumps({'type': 'error', 'content': f'Stream error: {str(e)}'}, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'steps': []}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── 历史记录 ───────────────────────────────────────────────────
@router.get("/history", response_model=list[StepResponse])
async def get_history(task_id: str, db: AsyncSession = Depends(get_db)):
    """获取指定 Task 的对话历史"""
    result = await db.execute(
        select(Step).where(Step.task_id == task_id).order_by(Step.created_at.asc())
    )
    return result.scalars().all()


# ── 获取 Step 中捕获的 DataFrame 预览数据 ──────────────────
@router.get("/steps/{step_id}/dataframe/{df_name}")
async def get_step_dataframe(
    step_id: str,
    df_name: str,
    db: AsyncSession = Depends(get_db),
):
    """返回某个 tool_use Step 中捕获的 DataFrame 数据（columns + rows）"""
    import os, json as _json
    # 查找 Step
    result = await db.execute(select(Step).where(Step.id == step_id))
    step = result.scalar_one_or_none()
    if not step:
        print('HEY, Step not found:', step_id)
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Step not found")
    if step.step_type != "tool_use" or not step.code_output:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Step has no code execution data")
    # 从 code_output 解析 dataframes 元数据，找到 capture_id
    try:
        output_data = _json.loads(step.code_output)
    except _json.JSONDecodeError:
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail="Invalid code_output format")
    dataframes_meta = output_data.get("dataframes", [])
    target = None
    for df_meta in dataframes_meta:
        if df_meta.get("name") == df_name:
            target = df_meta
            break
    if not target:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"DataFrame '{df_name}' not found in this step")
    capture_id = target.get("capture_id", "")
    capture_dir = os.path.join(UPLOADS_DIR, step.task_id, "captures")
    file_path = os.path.join(capture_dir, f"{capture_id}_{df_name}.json")
    if not os.path.exists(file_path):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Captured data file not found")
    # 读取并返回
    with open(file_path, "r", encoding="utf-8") as f:
        data = _json.load(f)
    return data  # {"columns": [...], "rows": [...]}

@router.get("/steps/{step_id}/dataframe/{df_name}/export")
async def export_step_dataframe(
    step_id: str,
    df_name: str,
    db: AsyncSession = Depends(get_db),
):
    """导出Step中捕获的DataFrame为Excel文件"""
    import pandas as pd
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    import tempfile
    from datetime import datetime
    
    # 1. 查找Step
    result = await db.execute(select(Step).where(Step.id == step_id))
    step = result.scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    
    if step.step_type != "tool_use" or not step.code_output:
        raise HTTPException(status_code=400, detail="Step has no code execution data")
    
    # 2. 从 code_output 解析 dataframes 元数据，找到 capture_id
    try:
        output_data = _json.loads(step.code_output)
    except _json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Invalid code_output format")
    
    dataframes_meta = output_data.get("dataframes", [])
    target = None
    for df_meta in dataframes_meta:
        if df_meta.get("name") == df_name:
            target = df_meta
            break
    
    if not target:
        raise HTTPException(status_code=404, detail=f"DataFrame '{df_name}' not found in this step")
    
    capture_id = target.get("capture_id", "")
    
    # 3. 组装文件路径
    capture_dir = os.path.join(UPLOADS_DIR, step.task_id, "captures")
    file_path = os.path.join(capture_dir, f"{capture_id}_{df_name}.json")
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Captured data file not found")
    
    # 安全检查
    real_path = os.path.realpath(file_path)
    uploads_real = os.path.realpath(UPLOADS_DIR)
    if not real_path.startswith(uploads_real):
        raise HTTPException(status_code=403, detail="Access denied")
    
    try:
        # 4. 读取JSON数据
        with open(file_path, "r", encoding="utf-8") as f:
            data = _json.load(f)
        
        # 5. 转换为DataFrame
        df = pd.DataFrame(data["rows"], columns=data["columns"])
        
        # 6. 写入临时Excel文件
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".xlsx", delete=False
        ) as tmp:
            df.to_excel(tmp.name, index=False, engine="openpyxl")
            tmp_path = tmp.name
        
        # 7. 生成文件名（包含时间戳）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{df_name}_{timestamp}.xlsx"
        
        # 8. 返回文件
        return FileResponse(
            path=tmp_path,
            filename=filename,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Export failed: {str(e)}")

# ── 删除单条 Step ──────────────────────────────────────────────
@router.delete("/steps/{step_id}")
async def delete_step(
    step_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    删除指定的单条 Step，同时清理关联的 Visualization 和 capture 文件。
    """
    from fastapi import HTTPException
    # 1. 查找目标 Step
    result = await db.execute(select(Step).where(Step.id == step_id))
    step = result.scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    # 2. 清理关联的 capture 文件
    if step.step_type == "tool_use" and step.code_output:
        try:
            output_data = _json.loads(step.code_output)
            for df_meta in output_data.get("dataframes", []):
                capture_id = df_meta.get("capture_id", "")
                df_name = df_meta.get("name", "")
                capture_dir = os.path.join(UPLOADS_DIR, step.task_id, "captures")
                file_path = os.path.join(capture_dir, f"{capture_id}_{df_name}.json")
                if os.path.exists(file_path):
                    os.remove(file_path)
        except (_json.JSONDecodeError, Exception):
            pass
    # 3. 删除关联的 Visualization
    viz_result = await db.execute(
        select(Visualization).where(Visualization.step_id == step_id)
    )
    for viz in viz_result.scalars().all():
        await db.delete(viz)
    # 4. 删除 Step
    await db.delete(step)
    await db.commit()
    return {"deleted_ids": [step_id]}


# ── 删除 Step 及其之后的所有 Step ──────────────────────────────
@router.delete("/steps/{step_id}")
async def delete_step_and_after(
    step_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    删除指定 Step 及其之后（按 created_at 排序）的所有 Step。
    用于用户清理不理想的对话/执行结果，避免污染上下文。
    """
    from fastapi import HTTPException
    # 1. 查找目标 Step
    result = await db.execute(select(Step).where(Step.id == step_id))
    target_step = result.scalar_one_or_none()
    if not target_step:
        raise HTTPException(status_code=404, detail="Step not found")
    print(f"[DELETE] Found target step: {step_id}, task_id={target_step.task_id}, created_at={target_step.created_at}")
    # 2. 查找该 Step 及其之后的所有 Step
    result = await db.execute(
        select(Step)
        .where(
            Step.task_id == target_step.task_id,
            Step.created_at >= target_step.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        )
        .order_by(Step.created_at.asc())
    )
    steps_to_delete = result.scalars().all()
    deleted_ids = [s.id for s in steps_to_delete]
    print(f"[DELETE] Steps to delete: {len(deleted_ids)} ids={deleted_ids}")

    # 3. 删除关联的 capture 文件（可选，清理磁盘）
    for step in steps_to_delete:
        if step.step_type == "tool_use" and step.code_output:
            try:
                output_data = _json.loads(step.code_output)
                for df_meta in output_data.get("dataframes", []):
                    capture_id = df_meta.get("capture_id", "")
                    df_name = df_meta.get("name", "")
                    capture_dir = os.path.join(UPLOADS_DIR, step.task_id, "captures")
                    file_path = os.path.join(capture_dir, f"{capture_id}_{df_name}.json")
                    if os.path.exists(file_path):
                        os.remove(file_path)
            except (_json.JSONDecodeError, Exception):
                pass  # 清理失败不影响主流程

    # 3.5 删除关联的 Visualization
    step_ids_to_delete = [s.id for s in steps_to_delete]
    if step_ids_to_delete:
        viz_result = await db.execute(
            select(Visualization).where(Visualization.step_id.in_(step_ids_to_delete))
        )
        for viz in viz_result.scalars().all():
            await db.delete(viz)

    # 4. 批量删除
    for step in steps_to_delete:
        await db.delete(step)
    
    print(f"[DELETE] About to commit, session.dirty={db.dirty}, session.deleted={db.deleted}")
    await db.commit()
    print(f"[DELETE] Commit done")
    # 5. 验证删除结果
    verify = await db.execute(select(Step).where(Step.id == step_id))
    still_exists = verify.scalar_one_or_none()
    print(f"[DELETE] Verify after commit: step still exists = {still_exists is not None}")
    return {"deleted_ids": deleted_ids}




# ── 重新生成：删除 Step 并返回需要重发的用户消息 ──────────────
@router.post("/steps/{step_id}/regenerate")
async def regenerate_from_step(
    step_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    找到指定 Step 之前最近的 user_message，
    删除该 user_message 及其之后的所有 Step，
    返回 user_message 内容供前端重新发送。
    """
    from fastapi import HTTPException

    # 1. 查找目标 Step
    result = await db.execute(select(Step).where(Step.id == step_id))
    target_step = result.scalar_one_or_none()
    if not target_step:
        raise HTTPException(status_code=404, detail="Step not found")

    task_id = target_step.task_id

    # 2. 查找该 Step 之前（含自身）最近的 user_message
    #    如果目标本身就是 user_message，则使用它
    if target_step.step_type == "user_message":
        anchor_step = target_step
    else:
        # 找到该 step 之前最近的 user_message
        result = await db.execute(
            select(Step)
            .where(
                Step.task_id == task_id,
                Step.step_type == "user_message",
                Step.created_at <= target_step.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            )
            .order_by(Step.created_at.desc())
            .limit(1)
        )
        anchor_step = result.scalar_one_or_none()
        if not anchor_step:
            raise HTTPException(
                status_code=400,
                detail="No user message found before this step"
            )

    user_message = anchor_step.content

    # 3. 删除 anchor_step 及其之后的所有 Step
    result = await db.execute(
        select(Step)
        .where(
            Step.task_id == task_id,
            Step.created_at >= anchor_step.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        )
        .order_by(Step.created_at.asc())
    )
    steps_to_delete = result.scalars().all()
    deleted_ids = [s.id for s in steps_to_delete]

    # 清理 capture 文件
    for step in steps_to_delete:
        if step.step_type == "tool_use" and step.code_output:
            try:
                output_data = _json.loads(step.code_output)
                for df_meta in output_data.get("dataframes", []):
                    capture_id = df_meta.get("capture_id", "")
                    df_name = df_meta.get("name", "")
                    capture_dir = os.path.join(UPLOADS_DIR, step.task_id, "captures")
                    file_path = os.path.join(capture_dir, f"{capture_id}_{df_name}.json")
                    if os.path.exists(file_path):
                        os.remove(file_path)
            except (_json.JSONDecodeError, Exception):
                pass

    for step in steps_to_delete:
        await db.delete(step)
    await db.commit()

    return {
        "user_message": user_message,
        "task_id": task_id,
        "deleted_ids": deleted_ids,
    }