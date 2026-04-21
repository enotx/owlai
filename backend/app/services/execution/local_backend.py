# backend/app/services/execution/local_backend.py

"""LocalSandboxBackend — 包装现有子进程沙箱"""

from __future__ import annotations

import glob
import json
import os

from app.config import UPLOADS_DIR
from app.services.execution.backend import ExecutionBackend
from app.services.execution.types import ExecutionContext
from app.services.sandbox import SandboxExecutionResult, execute_code_in_sandbox


class LocalSandboxBackend:
    """当前的本地子进程沙箱，包装为 ExecutionBackend 接口

    行为与直接调用 execute_code_in_sandbox 完全一致。
    """

    async def execute(self, ctx: ExecutionContext) -> SandboxExecutionResult:
        return await execute_code_in_sandbox(
            code=ctx.code,
            data_var_map=ctx.data_var_map,
            timeout=ctx.timeout,
            capture_dir=ctx.capture_dir or None,
            injected_envs=ctx.injected_envs or None,
            persisted_var_map=ctx.persisted_var_map or None,
        )

    async def interrupt(self, task_id: str) -> bool:
        # 本地子进程模式：进程生命周期在 execute 内部管理
        # 外部无法中断（靠超时机制兜底）
        return False

    async def shutdown(self, task_id: str) -> None:
        # 无状态，无需 shutdown
        pass

    async def list_variables(self, task_id: str) -> list[dict]:
        """从 persist/ 目录扫描变量元信息"""
        persist_dir = os.path.join(
            UPLOADS_DIR, task_id, "captures", "persist"
        )
        if not os.path.isdir(persist_dir):
            return []

        variables: list[dict] = []
        seen: set[str] = set()

        # Parquet 优先
        for fpath in sorted(glob.glob(os.path.join(persist_dir, "*.parquet"))):
            name = os.path.splitext(os.path.basename(fpath))[0]
            seen.add(name)
            try:
                import pyarrow.parquet as pq
                pf = pq.ParquetFile(fpath)
                schema = pf.schema_arrow
                meta = schema.metadata or {}
                persist_type = meta.get(b"__persist_type__", b"").decode()
                if persist_type == "series":
                    variables.append({
                        "name": name,
                        "type": "Series",
                        "rows": pf.metadata.num_rows,
                    })
                else:
                    cols = [schema.field(i).name for i in range(len(schema))]
                    variables.append({
                        "name": name,
                        "type": "DataFrame",
                        "rows": pf.metadata.num_rows,
                        "columns": cols[:20],
                    })
            except Exception:
                variables.append({"name": name, "type": "unknown"})

        # JSON 补充
        for fpath in sorted(glob.glob(os.path.join(persist_dir, "*.json"))):
            name = os.path.splitext(os.path.basename(fpath))[0]
            if name in seen:
                continue
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    blob = json.load(f)
                ptype = blob.get("__persist_type__", "dataframe")
                variables.append({"name": name, "type": ptype})
            except Exception:
                variables.append({"name": name, "type": "unknown"})

        return variables