# backend/app/services/execution/jupyter/backend.py

"""JupyterBackend — 远程 Jupyter kernel 执行后端"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

from app.services.execution.backend import ExecutionBackend
from app.services.execution.types import ExecutionContext
from app.services.execution.jupyter.probe import build_setup_code, build_probe_code
from app.services.execution.jupyter.uploader import JupyterUploader
from app.services.sandbox import SandboxExecutionResult

if TYPE_CHECKING:
    from app.services.execution.jupyter.session_manager import (
        KernelSessionManager,
        KernelSession,
    )

logger = logging.getLogger(__name__)


class JupyterBackend:
    """远程 Jupyter kernel 执行后端"""

    def __init__(
        self,
        session_manager: "KernelSessionManager",
        default_security_level: str = "lenient",
    ):
        self._sm = session_manager
        self._default_security_level = default_security_level
        self._uploader = JupyterUploader(
            self._sm.jupyter_url, self._sm.token
        )

    async def execute(self, ctx: ExecutionContext) -> SandboxExecutionResult:
        """执行代码，返回标准 SandboxExecutionResult"""
        session = await self._sm.get_or_create(ctx.task_id)
        session.status = "busy"

        try:
            # 1. 首次连接：注入 helper 函数
            if not session.setup_done:
                await self._inject_setup(session, ctx)
                session.setup_done = True

            # 2. 数据注入（仅新增的数据源）
            await self._inject_data(session, ctx)

            # 3. 安全检查（可选）
            # security_level = ctx.security_level or self._default_security_level
            # if security_level == "strict":
            #     from app.services.code_security import check_code_security

            #     result = check_code_security(ctx.code)
            #     if not result.safe:
            #         return self._blocked_result(result.violations)

            # 4. 执行用户代码
            exec_output = await session.wire.execute_code(
                session.ws, ctx.code, timeout=ctx.timeout
            )

            # 5. 执行探针代码，收集 DataFrame / chart / variable 信息
            probe_result = await self._run_probe(session)

            # 6. 组装 SandboxExecutionResult
            return self._build_result(exec_output, probe_result, ctx)

        except Exception as e:
            logger.error(f"JupyterBackend execution error: {e}")
            return {
                "success": False,
                "output": None,
                "error": f"Jupyter execution error: {str(e)}",
                "execution_time": 0.0,
                "dataframes": [],
                "persisted_vars": {},
                "charts": [],
                "maps": [],
                "artifacts": [],
            }
        finally:
            session.status = "idle"
            session.last_activity = __import__("time").time()

    async def _inject_setup(
        self, session: "KernelSession", ctx: ExecutionContext
    ) -> None:
        """首次连接时注入 helper 函数"""
        setup_code = build_setup_code()

        # 注入环境变量（通过 os.environ）
        if ctx.injected_envs:
            env_lines = []
            for key, value in ctx.injected_envs.items():
                if key == "__allowed_modules__":
                    continue  # Jupyter 模式下不限制 import
                # 转义单引号
                safe_value = value.replace("'", "\\'")
                env_lines.append(f"_os.environ['{key}'] = '{safe_value}'")
            if env_lines:
                setup_code += "\n" + "\n".join(env_lines)

        result = await session.wire.execute_code(
            session.ws, setup_code, timeout=30.0, silent=True
        )

        if not result["success"]:
            raise RuntimeError(
                f"Failed to inject setup code: {result.get('error')}"
            )

        # 检查 __OWL_SETUP_OK__ 标记
        if "__OWL_SETUP_OK__" not in (result.get("output") or ""):
            raise RuntimeError("Setup code did not print __OWL_SETUP_OK__")

        logger.info(f"Injected setup code into kernel {session.kernel_id}")

    async def _inject_data(
        self, session: "KernelSession", ctx: ExecutionContext
    ) -> None:
        """将 data_var_map 中的文件推送到远端 kernel"""
        for var_name, local_path in ctx.data_var_map.items():
            # 检查是否已上传过（避免重复）
            if local_path in session.uploaded_files:
                remote_path = session.uploaded_files[local_path]
                logger.debug(f"Reusing uploaded file: {var_name} → {remote_path}")
            else:
                # 上传文件
                try:
                    remote_path = await self._uploader.upload_file(local_path)
                    session.uploaded_files[local_path] = remote_path
                except Exception as e:
                    logger.error(f"Failed to upload {local_path}: {e}")
                    continue

            # 检查远端是否已有此变量（避免重复加载）
            check_code = f"'{var_name}' in dir()"
            check_result = await session.wire.execute_code(
                session.ws, check_code, timeout=5.0, silent=True
            )
            if "True" in (check_result.get("output") or ""):
                logger.debug(f"Variable {var_name} already exists in kernel")
                continue

            # 生成加载代码
            ext = local_path.lower().split(".")[-1]
            if ext == "csv":
                load_code = (
                    f'{var_name} = pd.read_csv("{remote_path}", encoding="utf-8-sig")\n'
                    f'{var_name}.columns = {var_name}.columns.str.strip()'
                )
            elif ext in ("xlsx", "xls"):
                load_code = (
                    f'{var_name} = pd.read_excel("{remote_path}")\n'
                    f'{var_name}.columns = {var_name}.columns.str.strip()\n'
                    f'{var_name}_sheets = pd.read_excel("{remote_path}", sheet_name=None)\n'
                    f'for __sheet_key in {var_name}_sheets: '
                    f'{var_name}_sheets[__sheet_key].columns = {var_name}_sheets[__sheet_key].columns.str.strip()'
                )
            else:
                logger.warning(f"Unsupported file type for {var_name}: {ext}")
                continue

            # 执行加载代码
            load_result = await session.wire.execute_code(
                session.ws, load_code, timeout=60.0, silent=True
            )
            if not load_result["success"]:
                logger.error(
                    f"Failed to load {var_name}: {load_result.get('error')}"
                )

    async def _run_probe(self, session: "KernelSession") -> dict:
        """执行探针代码，收集变量/DataFrame/图表信息"""
        probe_code = build_probe_code()
        result = await session.wire.execute_code(
            session.ws, probe_code, timeout=30.0, silent=True
        )

        if not result["success"]:
            logger.warning(f"Probe execution failed: {result.get('error')}")
            return {"dataframes": [], "charts": [], "maps": [], "variables": []}

        # 解析 __OWL_PROBE__ 标记后的 JSON
        output = result.get("output") or ""
        marker = "__OWL_PROBE__"
        if marker not in output:
            logger.warning("Probe did not print __OWL_PROBE__ marker")
            return {"dataframes": [], "charts": [], "maps": [], "variables": []}

        try:
            json_str = output.split(marker, 1)[1].strip()
            probe_data = json.loads(json_str)
            return probe_data
        except (json.JSONDecodeError, IndexError) as e:
            logger.error(f"Failed to parse probe result: {e}")
            return {"dataframes": [], "charts": [], "maps": [], "variables": []}

    def _build_result(
        self,
        exec_output: dict,
        probe_result: dict,
        ctx: ExecutionContext,
    ) -> SandboxExecutionResult:
        """组装 SandboxExecutionResult"""
        # 写入 persist/ 目录的元信息文件（供上层 base.py 扫描）
        persisted_vars: dict[str, str] = {}
        if ctx.capture_dir:
            persist_dir = os.path.join(ctx.capture_dir, "persist")
            os.makedirs(persist_dir, exist_ok=True)

            for df_info in probe_result.get("dataframes", []):
                meta_path = os.path.join(persist_dir, f"{df_info['name']}.json")
                meta = {
                    "__persist_type__": "dataframe",
                    "__source__": "jupyter_kernel",
                    "columns": df_info["columns"],
                    "rows": [],  # 空，仅元信息
                    "row_count": df_info["row_count"],
                }
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta, f)
                persisted_vars[df_info["name"]] = meta_path

        return {
            "success": exec_output["success"],
            "output": exec_output.get("output"),
            "error": exec_output.get("error"),
            "execution_time": exec_output["execution_time"],
            "dataframes": probe_result.get("dataframes", []),
            "persisted_vars": persisted_vars,
            "charts": probe_result.get("charts", []),
            "maps": probe_result.get("maps", []),
            "artifacts": [],  # Jupyter 模式下 artifact 存在远端，暂不回传
        }

    def _blocked_result(self, violations: list[str]) -> SandboxExecutionResult:
        """安全检查失败时返回的结果"""
        error_msg = (
            "🛡️ Code blocked by security check:\n"
            + "\n".join(f"  • {v}" for v in violations)
        )
        return {
            "success": False,
            "output": None,
            "error": error_msg,
            "execution_time": 0.0,
            "dataframes": [],
            "persisted_vars": {},
            "charts": [],
            "maps": [],
            "artifacts": [],
        }

    async def interrupt(self, task_id: str) -> bool:
        """中断指定 task 的执行"""
        return await self._sm.interrupt(task_id)

    async def shutdown(self, task_id: str) -> None:
        """关闭 task 对应的 kernel session"""
        await self._sm.shutdown(task_id)

    async def list_variables(self, task_id: str) -> list[dict]:
        """列出当前 kernel 中的变量（通过探针）"""
        session = self._sm._sessions.get(task_id)
        if not session:
            return []

        try:
            probe_result = await self._run_probe(session)
            variables = probe_result.get("variables", [])
            dataframes = probe_result.get("dataframes", [])
            # 合并返回
            return variables + [
                {"name": df["name"], "type": "DataFrame", "rows": df["row_count"]}
                for df in dataframes
            ]
        except Exception as e:
            logger.error(f"Failed to list variables: {e}")
            return []