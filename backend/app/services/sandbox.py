# backend/app/services/sandbox.py
"""
安全代码执行沙箱：在子进程中执行 AI 生成的 Pandas 代码。
安全策略：
1. 子进程隔离 — 崩溃不影响主进程
2. 超时控制 — subprocess.run timeout
3. 白名单 import — 只允许数据分析相关模块
4. 禁止危险内建函数 — open/exec/eval/__import__
5. 输出长度限制 — 防止巨量输出撑爆内存
"""
import asyncio
import json
import os
import sys
import tempfile
import textwrap
import time
from typing import Any
from app.services.code_security import check_code_security
from app.config import PYTHON_EXECUTABLE, DATA_DIR


# 沙箱参数
SANDBOX_TIMEOUT = 60  # 秒
MAX_OUTPUT_LENGTH = 50_000  # 最大输出字符数

def _build_sandbox_script(
    code: str,
    csv_var_map: dict[str, str],
    capture_dir: str | None = None,
) -> str:
    """
    构建在子进程中执行的 Python 脚本。
    csv_var_map: {variable_name: absolute_file_path}
    capture_dir: 若提供，执行后扫描命名空间中的 DataFrame 并序列化到此目录
    """
    # CSV 加载语句
    loader_lines = []
    for var_name, fpath in csv_var_map.items():
        escaped_path = fpath.replace("\\", "\\\\")
        loader_lines.append(f'    {var_name} = __pd.read_csv("{escaped_path}")')
    loader_code = "\n".join(loader_lines)
    # namespace 注入语句
    namespace_inject = chr(10).join(
        f"    _namespace['{var}'] = {var}" for var in csv_var_map.keys()
    )
    # 已有 CSV 变量名集合（排除这些，只捕获用户代码新生成的 DF）
    preloaded_var_names = set(csv_var_map.keys())
    preloaded_repr = repr(preloaded_var_names)
    # capture_dir 路径（转义）
    capture_dir_escaped = (capture_dir or "").replace("\\", "\\\\")
    script = textwrap.dedent(f"""\
    import sys
    import json
    import os as _os
    from io import StringIO
    # ── 白名单 import 机制 ──────────────────────────────────
    _ALLOWED_MODULES = {{
        'pandas', 'numpy', 'math', 'statistics', 'collections',
        'itertools', 'functools', 'operator', 'string', 're',
        'datetime', 'json', 'decimal', 'fractions', 'textwrap',
        'collections.abc', 'typing', 'numbers',
    }}
    _original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__
    def _safe_import(name, *args, **kwargs):
        top_level = name.split('.')[0]
        if top_level not in _ALLOWED_MODULES:
            raise ImportError(f"Import of '{{name}}' is not allowed in sandbox")
        return _original_import(name, *args, **kwargs)
    # ── 安全内建 ────────────────────────────────────────────
    import builtins as _builtins_mod
    _safe_builtins = {{}}
    _BLOCKED = {{'exec', 'eval', 'compile', '__import__', 'open',
                 'input', 'breakpoint', 'exit', 'quit', 'globals',
                 'locals', 'vars', 'setattr', 'delattr',
                 'memoryview', 'classmethod', 'staticmethod'}}
    for _k in dir(_builtins_mod):
        if _k not in _BLOCKED and not _k.startswith('_'):
            _safe_builtins[_k] = getattr(_builtins_mod, _k)
    _safe_builtins['__import__'] = _safe_import
    _safe_builtins['print'] = print
    _safe_builtins['range'] = range
    _safe_builtins['len'] = len
    _safe_builtins['enumerate'] = enumerate
    _safe_builtins['zip'] = zip
    _safe_builtins['map'] = map
    _safe_builtins['filter'] = filter
    _safe_builtins['sorted'] = sorted
    _safe_builtins['reversed'] = reversed
    _safe_builtins['list'] = list
    _safe_builtins['dict'] = dict
    _safe_builtins['set'] = set
    _safe_builtins['tuple'] = tuple
    _safe_builtins['str'] = str
    _safe_builtins['int'] = int
    _safe_builtins['float'] = float
    _safe_builtins['bool'] = bool
    _safe_builtins['type'] = type
    _safe_builtins['isinstance'] = isinstance
    _safe_builtins['issubclass'] = issubclass
    _safe_builtins['hasattr'] = hasattr
    _safe_builtins['repr'] = repr
    _safe_builtins['abs'] = abs
    _safe_builtins['round'] = round
    _safe_builtins['min'] = min
    _safe_builtins['max'] = max
    _safe_builtins['sum'] = sum
    _safe_builtins['any'] = any
    _safe_builtins['all'] = all
    _safe_builtins['slice'] = slice
    _safe_builtins['hash'] = hash
    _safe_builtins['id'] = id
    _safe_builtins['None'] = None
    _safe_builtins['True'] = True
    _safe_builtins['False'] = False
    _safe_builtins['Exception'] = Exception
    _safe_builtins['ValueError'] = ValueError
    _safe_builtins['TypeError'] = TypeError
    _safe_builtins['KeyError'] = KeyError
    _safe_builtins['IndexError'] = IndexError
    _safe_builtins['AttributeError'] = AttributeError
    _safe_builtins['RuntimeError'] = RuntimeError
    _safe_builtins['StopIteration'] = StopIteration
    _safe_builtins['ZeroDivisionError'] = ZeroDivisionError
    _safe_builtins['NotImplementedError'] = NotImplementedError
    _safe_builtins['dir'] = dir
    _safe_builtins['getattr'] = getattr
    _safe_builtins['super'] = super
    _safe_builtins['property'] = property
    _safe_builtins['frozenset'] = frozenset
    _safe_builtins['bytes'] = bytes
    _safe_builtins['bytearray'] = bytearray
    _safe_builtins['complex'] = complex
    _safe_builtins['format'] = format
    _safe_builtins['iter'] = iter
    _safe_builtins['next'] = next
    _safe_builtins['callable'] = callable
    _safe_builtins['chr'] = chr
    _safe_builtins['ord'] = ord
    _safe_builtins['hex'] = hex
    _safe_builtins['oct'] = oct
    _safe_builtins['bin'] = bin
    _safe_builtins['pow'] = pow
    _safe_builtins['divmod'] = divmod
    _safe_builtins['object'] = object
    _safe_builtins['ArithmeticError'] = ArithmeticError
    _safe_builtins['LookupError'] = LookupError
    _safe_builtins['OverflowError'] = OverflowError
    _safe_builtins['UnicodeError'] = UnicodeError
    _safe_builtins['UnicodeDecodeError'] = UnicodeDecodeError
    _safe_builtins['UnicodeEncodeError'] = UnicodeEncodeError
    # ── 预加载数据分析库 ────────────────────────────────────
    import pandas as __pd
    import numpy as __np
    # ── 加载 CSV 数据 ──────────────────────────────────────
{loader_code}
    # ── 捕获 stdout ────────────────────────────────────────
    _stdout_capture = StringIO()
    _original_stdout = sys.stdout
    sys.stdout = _stdout_capture
    # ── 构造受限命名空间 ───────────────────────────────────
    _namespace = {{
        '__builtins__': _safe_builtins,
        'pd': __pd,
        'np': __np,
        'pandas': __pd,
        'numpy': __np,
    }}
    # 注入 DataFrame 变量
{namespace_inject}
    # ── 执行用户代码 ───────────────────────────────────────
    _error = None
    try:
        exec(
            {repr(code)},
            _namespace,
            _namespace,
        )
    except Exception as _e:
        import traceback as _tb
        _error = _tb.format_exc()
    # ── 输出结果 ───────────────────────────────────────────
    sys.stdout = _original_stdout
    _output = _stdout_capture.getvalue()
    # 截断过长输出
    _MAX = {MAX_OUTPUT_LENGTH}
    if len(_output) > _MAX:
        _output = _output[:_MAX] + "\\n\\n[Output truncated at {{_MAX}} chars]"
    # ── 捕获命名空间中的 DataFrame ─────────────────────────
    _captured_dfs = []
    _capture_dir = "{capture_dir_escaped}"
    _PRELOADED = {preloaded_repr}
    _PRIORITY_PREFIXES = ['result', 'output', 'summary']
    _MAX_CAPTURE = 5  # 最多捕获的DataFrame个数
    _MAX_ROWS = 500
    _SKIP_KEYS = {{'__builtins__', 'pd', 'np', 'pandas', 'numpy'}}
    if _capture_dir:
        # 收集所有新生成的 DataFrame（排除预加载的 CSV 变量）
        _all_dfs = {{}}
        for _k, _v in _namespace.items():
            if _k.startswith('_') or _k in _SKIP_KEYS or _k in _PRELOADED:
                continue
            if isinstance(_v, __pd.DataFrame):
                _all_dfs[_k] = _v
        # 排序：前缀模糊匹配优先，精确命中最优先
        _ordered = []
        _priority_set = set()
        # 第一轮：精确匹配（result / output / summary）
        for _prefix in _PRIORITY_PREFIXES:
            if _prefix in _all_dfs and _prefix not in _priority_set:
                _ordered.append(_prefix)
                _priority_set.add(_prefix)
        # 第二轮：前缀匹配（result_xxx / output_xxx / summary_xxx）
        for _prefix in _PRIORITY_PREFIXES:
            for _k in sorted(_all_dfs.keys()):
                if _k not in _priority_set and (_k.startswith(_prefix + '_') or _k.startswith(_prefix + '-')):
                    _ordered.append(_k)
                    _priority_set.add(_k)
        # 第三轮：其余 DataFrame 按原始顺序
        for _k in _all_dfs:
            if _k not in _priority_set:
                _ordered.append(_k)
        _ordered = _ordered[:_MAX_CAPTURE]
        if _ordered:
            _os.makedirs(_capture_dir, exist_ok=True)
            for _dfname in _ordered:
                try:
                    _df = _all_dfs[_dfname]
                    _preview = _df.head(_MAX_ROWS)
                    _cols = [str(c) for c in _preview.columns.tolist()]
                    # 处理 NaN/Infinity → None，日期等 → str
                    _clean = _preview.where(__pd.notnull(_preview), None)
                    _rows = json.loads(_clean.to_json(orient='records', default_handler=str))
                    _meta = {{
                        "name": _dfname,
                        "row_count": len(_df),
                        "preview_count": len(_preview),
                        "columns": _cols,
                    }}
                    _fpath = _os.path.join(_capture_dir, _dfname + ".json")
                    with open(_fpath, 'w', encoding='utf-8') as _f:
                        json.dump({{"columns": _cols, "rows": _rows}}, _f, ensure_ascii=False, default=str)
                    _captured_dfs.append(_meta)
                except Exception as _cap_err:
                    # 捕获失败不影响主结果
                    pass
    result = {{
        "success": _error is None,
        "output": _output if _output else None,
        "error": _error,
        "dataframes": _captured_dfs,
    }}
    print(json.dumps(result, ensure_ascii=False))
    """)
    return script

async def execute_code_in_sandbox(
    code: str,
    csv_var_map: dict[str, str],
    timeout: int = SANDBOX_TIMEOUT,
    capture_dir: str | None = None,
) -> dict[str, Any]:
    """
    在子进程中安全执行代码。
    Args:
        code: 要执行的 Python 代码
        csv_var_map: {变量名: CSV文件绝对路径}
        timeout: 超时秒数
        capture_dir: 若提供，沙箱执行后将捕获的 DataFrame 以 JSON 写入此目录
    Returns:
        {"success": bool, "output": str|None, "error": str|None,
         "execution_time": float, "dataframes": list[dict]}
    """

    # ── AST 静态安全检查（在子进程之前拦截） ──────────────
    security_result = check_code_security(code)
    if not security_result.safe:
        return {
            "success": False,
            "output": None,
            "error": (
                "🛡️ Code blocked by security check:\n"
                + "\n".join(f"  • {v}" for v in security_result.violations)
            ),
            "execution_time": 0.0,
            "dataframes": [],
        }


    # 写入临时脚本文件
    script_content = _build_sandbox_script(code, csv_var_map, capture_dir)

    tmp_file = None
    start_time = time.monotonic()
    try:
        # 创建临时文件（不自动删除，手动清理）
        tmp_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        )
        tmp_file.write(script_content)
        tmp_file.flush()
        tmp_file.close()
        # 在子进程中执行
        proc = await asyncio.create_subprocess_exec(
            PYTHON_EXECUTABLE, tmp_file.name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # 设置工作目录为DATA目录，确保相对路径能找到 data/uploads
            cwd=DATA_DIR, # 其实UPLOADS_DIR更准确，以后再说
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            elapsed = time.monotonic() - start_time
            return {
                "success": False,
                "output": None,
                "error": f"⏱️ Code execution timed out after {timeout}s",
                "execution_time": elapsed,
                "dataframes": [],
            }

        elapsed = time.monotonic() - start_time
        stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()

        # 尝试解析脚本最后输出的 JSON 结果
        if stdout_text:
            # 取最后一行 JSON（前面可能有 print 输出）
            lines = stdout_text.split("\n")
            for line in reversed(lines):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        result = json.loads(line)
                        result["execution_time"] = elapsed
                        result.setdefault("dataframes", [])
                        # 如果沙箱脚本自身 print 的内容在 JSON 之前，也要拼上
                        prefix_lines = []
                        for l in lines:
                            if l.strip() == line:
                                break
                            prefix_lines.append(l)
                        if prefix_lines and result.get("output"):
                            result["output"] = "\n".join(prefix_lines) + "\n" + result["output"]
                        elif prefix_lines:
                            result["output"] = "\n".join(prefix_lines)
                        return result
                    except json.JSONDecodeError:
                        continue

        # JSON 解析失败 → 回退
        return {
            "success": False,
            "output": stdout_text or None,
            "error": stderr_text or "Unknown execution error (no JSON output)",
            "execution_time": elapsed,
            "dataframes": [],
        }

    except Exception as e:
        elapsed = time.monotonic() - start_time
        return {
            "success": False,
            "output": None,
            "error": f"Sandbox setup error: {str(e)}",
            "execution_time": elapsed,
            "dataframes": [],
        }
    finally:
        # 清理临时文件
        if tmp_file and os.path.exists(tmp_file.name):
            try:
                os.unlink(tmp_file.name)
            except OSError:
                pass