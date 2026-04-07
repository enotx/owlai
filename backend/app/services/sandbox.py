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
import uuid
from typing import Any
from app.services.code_security import check_code_security
from app.config import PYTHON_EXECUTABLE, UPLOADS_DIR


# 沙箱参数
SANDBOX_TIMEOUT = 60  # 秒
SANDBOX_TOTAL_TIMEOUT = 7200  # 2小时总超时（硬上限）
SANDBOX_IDLE_TIMEOUT = 90     # 90秒无活动视为挂死

MAX_OUTPUT_LENGTH = 50_000  # 最大输出字符数

def _build_sandbox_script(
    code: str,
    data_var_map: dict[str, str],
    capture_dir: str | None = None,
    extra_allowed_modules: list[str] | None = None,
    persisted_var_map: dict[str, str] | None = None,  # 上一轮持久化的变量 {var_name: .parquet/.json path}
    heartbeat_file: str | None = None,
) -> str:
    """
    构建在子进程中执行的 Python 脚本。
    data_var_map: {variable_name: absolute_file_path}
    capture_dir: 若提供，执行后扫描命名空间中的 DataFrame 并序列化到此目录
    """
    # 数据加载语句（支持 CSV 和 Excel）
    loader_lines = []
    for var_name, fpath in data_var_map.items():
        escaped_path = fpath.replace("\\", "\\\\")
        
        # 根据文件扩展名选择加载器
        ext = fpath.lower().split('.')[-1]
        
        if ext == 'csv':
            loader_lines.append(f'{var_name} = __pd.read_csv("{escaped_path}", encoding="utf-8-sig")')
            loader_lines.append(f'{var_name}.columns = {var_name}.columns.str.strip()')
        
        elif ext in ('xlsx', 'xls'):
            # 加载默认 sheet（第一个）到主变量
            loader_lines.append(f'{var_name} = __pd.read_excel("{escaped_path}")')
            loader_lines.append(f'{var_name}.columns = {var_name}.columns.str.strip()')
            # 加载所有 sheets 到字典变量
            loader_lines.append(f'{var_name}_sheets = __pd.read_excel("{escaped_path}", sheet_name=None)')
            loader_lines.append(f'for __sheet_key in {var_name}_sheets: {var_name}_sheets[__sheet_key].columns = {var_name}_sheets[__sheet_key].columns.str.strip()')
        
        else:
            # 未知格式，尝试 CSV
            loader_lines.append(f'{var_name} = __pd.read_csv("{escaped_path}", encoding="utf-8-sig")')
            loader_lines.append(f'{var_name}.columns = {var_name}.columns.str.strip()')
    
    loader_code = "\n".join(loader_lines)
    # ── 从上一轮持久化的 JSON 恢复变量（支持多种类型） ──
    json_loader_lines = []
    json_var_names: set[str] = set()
    if persisted_var_map:
        for var_name, json_path in persisted_var_map.items():
            escaped = json_path.replace("\\", "\\\\")
            json_loader_lines.append(
                f'{var_name} = __restore_var("{escaped}")'
            )
            json_var_names.add(var_name)
    json_loader_code = "\n".join(json_loader_lines)
    
    # namespace 注入语句（包括 _sheets 变量）
    namespace_inject_lines = []
    for var in data_var_map.keys():
        namespace_inject_lines.append(f"_namespace['{var}'] = {var}")
        # 如果是 Excel，也注入 _sheets 变量
        fpath = data_var_map[var]
        ext = fpath.lower().split('.')[-1]
        if ext in ('xlsx', 'xls'):
            namespace_inject_lines.append(f"_namespace['{var}_sheets'] = {var}_sheets")
    
    # 追加 JSON 恢复变量的注入
    for var_name in json_var_names:
        namespace_inject_lines.append(f"_namespace['{var_name}'] = {var_name}")
    namespace_inject = "\n".join(namespace_inject_lines)
    
    # 预加载变量名集合（包括 _sheets 和 JSON 恢复的变量）
    preloaded_var_names = set(data_var_map.keys())
    preloaded_var_names.update(json_var_names)  # JSON 恢复的变量也视为"预加载"，避免重复捕获

    for var in list(data_var_map.keys()):
        fpath = data_var_map[var]
        ext = fpath.lower().split('.')[-1]
        if ext in ('xlsx', 'xls'):
            preloaded_var_names.add(f"{var}_sheets")
    
    preloaded_repr = repr(preloaded_var_names)    # 已有 CSV 变量名集合（排除这些，只捕获用户代码新生成的 DF）
    # capture_dir 路径（转义）
    capture_dir_escaped = (capture_dir or "").replace("\\", "\\\\")

    # 心跳线程代码（注入到用户代码执行前）
    heartbeat_code = ""
    if heartbeat_file:
        escaped_hb = heartbeat_file.replace("\\", "\\\\")
        heartbeat_code = f"""\
# ── 心跳线程（每10秒写入心跳文件） ──────────────────
import threading as _threading
import time as _time_mod
_heartbeat_file = "{escaped_hb}"
_heartbeat_stop = _threading.Event()
def _heartbeat_worker():
    while not _heartbeat_stop.is_set():
        try:
            with open(_heartbeat_file, 'w') as _hf:
                _hf.write(str(_time_mod.time()))
            _hf_flush = True
        except Exception:
            pass
        _heartbeat_stop.wait(10)  # 每10秒写一次
_heartbeat_thread = _threading.Thread(target=_heartbeat_worker, daemon=True)
_heartbeat_thread.start()
        """
    heartbeat_code = heartbeat_code

    script = f"""\
import sys
import json
import os as _os
from io import StringIO
# ── 白名单 import 机制 ──────────────────────────────────
_ALLOWED_MODULES = {{
    'pandas', 'numpy', 'math', 'statistics', 'collections',
    'itertools', 'functools', 'operator', 'string', 're',
    'datetime', 'json', 'decimal', 'fractions', 'textwrap',
    'collections.abc', 'typing', 'numbers', 'hashlib', 'random',
    'sklearn', 'scipy', 'time', 'xgboost', 'lightgbm', 'catboost',
    'duckdb', 'pyarrow'
}}
# 动态追加 Skill 声明的额外模块
_ALLOWED_MODULES.update({repr(set(extra_allowed_modules or []))})

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
# 提供受限的环境变量读取能力（仅限 Skill 注入的变量）
def _safe_getenv(key, default=None):
    return _os.environ.get(key, default)
_safe_builtins['getenv'] = _safe_getenv
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
import json as __json_mod
import pyarrow as __pa
import pyarrow.parquet as __pq
# ── 通用变量恢复函数 ────────────────────────────────────
def __restore_var(__fpath):
    # ── Parquet 格式（新版） ─────────────────────────────
    if __fpath.endswith(".parquet"):
        _table = __pq.read_table(__fpath)
        _meta = _table.schema.metadata or {{}}
        # 判断是否为 Series（写入时打了标记）
        if _meta.get(b'__persist_type__') == b'series':
            _df = _table.to_pandas()
            _sname_bytes = _meta.get(b'__series_name__', b'')
            _sname = _sname_bytes.decode('utf-8') if _sname_bytes else None
            return _df.iloc[:, 0].rename(_sname or None)
        # 普通 DataFrame
        return _table.to_pandas()

    # ── JSON 格式（向后兼容旧版持久化文件） ──────────────
    with open(__fpath, "r", encoding="utf-8") as __rf:
        __blob = __json_mod.load(__rf)
    __ptype = __blob.get("__persist_type__")

    # 向后兼容：旧格式无 __persist_type__，视为 DataFrame
    if __ptype is None or __ptype == "dataframe":
        __cols = __blob.get("columns", [])
        __rows = __blob.get("rows", [])
        if __rows and isinstance(__rows[0], dict):
            __df = __pd.DataFrame(__rows)
            if __cols:
                __valid_cols = [c for c in __cols if c in __df.columns]
                __extra_cols = [c for c in __df.columns if c not in __cols]
                __df = __df[__valid_cols + __extra_cols]
        elif __cols:
            __df = __pd.DataFrame(__rows, columns=__cols)
        else:
            __df = __pd.DataFrame(__rows)
        return __df
    if __ptype == "series":
        __s = __pd.Series(__blob["data"], name=__blob.get("name"))
        __dt = __blob.get("dtype")
        if __dt:
            try:
                __s = __s.astype(__dt)
            except Exception:
                pass
        return __s
    if __ptype == "ndarray":
        __arr = __np.array(__blob["data"])
        __dt = __blob.get("dtype")
        if __dt:
            try:
                __arr = __arr.astype(__dt)
            except Exception:
                pass
        return __arr
    if __ptype == "numpy_scalar":
        __dt = __blob.get("dtype", "float64")
        try:
            return __np.dtype(__dt).type(__blob["value"])
        except Exception:
            return __blob["value"]
    return __blob.get("value")

# ── 加载 CSV 数据 ──────────────────────────────────────
{loader_code}
# ── 恢复上一轮持久化的 DataFrame ──────────────────────
{json_loader_code}
# ── 启动心跳线程 ──────────────────────────────────────
{heartbeat_code}
# ── 沙箱内 create_chart() 函数 ─────────────────────────
_captured_charts = []
_CHART_CAPTURE_DIR = "{capture_dir_escaped}"
def _sandbox_create_chart(__title, __chart_type, __option):
    \"\"\"沙箱内可调用的图表创建函数，捕获 ECharts option\"\"\"
    import json as _cjson
    # 深拷贝并序列化 option（将 numpy/pandas 类型转为 Python 原生类型）
    def _serialize(__obj):
        if isinstance(__obj, dict):
            return {{k: _serialize(v) for k, v in __obj.items()}}
        if isinstance(__obj, (list, tuple)):
            return [_serialize(v) for v in __obj]
        if hasattr(__obj, 'item'):  # numpy scalar
            return __obj.item()
        if hasattr(__obj, 'tolist'):  # numpy array / pandas series
            return __obj.tolist()
        if __obj is True:
            return True
        if __obj is False:
            return False
        if __obj is None:
            return None
        if isinstance(__obj, (int, float, str)):
            return __obj
        return str(__obj)
    _safe_option = _serialize(__option)
    _chart_meta = {{
        "title": str(__title),
        "chart_type": str(__chart_type),
        "option": _safe_option,
    }}
    _captured_charts.append(_chart_meta)
    # 同时写入文件（防止进程异常丢失）
    if _CHART_CAPTURE_DIR:
        _chart_dir = _os.path.join(_CHART_CAPTURE_DIR, "charts")
        _os.makedirs(_chart_dir, exist_ok=True)
        _chart_path = _os.path.join(_chart_dir, f"chart_{{len(_captured_charts)-1}}.json")
        with open(_chart_path, 'w', encoding='utf-8') as _cf:
            _cjson.dump(_chart_meta, _cf, ensure_ascii=False, default=str)
    print(f"[Chart created: {{__title}}]")
_captured_maps = []
def _sandbox_create_map(__title, __map_config):
    # 沙箱内可调用的地图创建函数，捕获 Leaflet 配置
    import json as _mjson
    # 序列化 map_config（处理 numpy/pandas 类型）
    def _serialize(__obj):
        if isinstance(__obj, dict):
            return {{k: _serialize(v) for k, v in __obj.items()}}
        if isinstance(__obj, (list, tuple)):
            return [_serialize(v) for v in __obj]
        if hasattr(__obj, 'item'):  # numpy scalar
            return __obj.item()
        if hasattr(__obj, 'tolist'):  # numpy array / pandas series
            return __obj.tolist()
        if __obj is True:
            return True
        if __obj is False:
            return False
        if __obj is None:
            return None
        if isinstance(__obj, (int, float, str)):
            return __obj
        return str(__obj)
    _safe_config = _serialize(__map_config)
    _map_meta = {{
        "title": str(__title),
        "config": _safe_config,
    }}
    _captured_maps.append(_map_meta)
    # 写入文件（防止进程异常丢失）
    if _CHART_CAPTURE_DIR:
        _map_dir = _os.path.join(_CHART_CAPTURE_DIR, "maps")
        _os.makedirs(_map_dir, exist_ok=True)
        _map_path = _os.path.join(_map_dir, f"map_{{len(_captured_maps)-1}}.json")
        with open(_map_path, 'w', encoding='utf-8') as _mf:
            _mjson.dump(_map_meta, _mf, ensure_ascii=False, default=str)
    print(f"[Map created: {{__title}}]")

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
    'create_chart': _sandbox_create_chart,
    'create_map': _sandbox_create_map,
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
finally:
    # 停止心跳线程（如果存在）
    try:
        _heartbeat_stop.set()
    except NameError:
        pass

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
_MAX_CAPTURE = 10  # 最多捕获的DataFrame个数
_MAX_ROWS = 50000  # 每个DataFrame最多捕获的行数（防止巨量数据）
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
# ── 持久化所有新变量到 persist/ 目录（供下一轮复用） ──────
# DataFrame / Series → Parquet（高速、类型保真）
# ndarray / scalar / 基础类型 → JSON（体积极小，无需 Parquet）
_persisted_vars = {{}}
_MAX_PERSIST = 30
_MAX_PERSIST_ROWS = 200000
_MAX_PARQUET_SIZE = 50 * 1024 * 1024   # 单个 Parquet 文件上限 50 MB
_MAX_JSON_VALUE_SIZE = 500000           # JSON 序列化后字符串上限
if _capture_dir:
    _persist_dir = _os.path.join(_capture_dir, "persist")
    _os.makedirs(_persist_dir, exist_ok=True)
    _persist_count = 0
    for _k, _v in _namespace.items():
        if _persist_count >= _MAX_PERSIST:
            break
        if _k.startswith('_') or _k in _SKIP_KEYS or _k in _PRELOADED:
            continue
        try:
            # ── DataFrame → Parquet ─────────────────────
            if isinstance(_v, __pd.DataFrame):
                _slice = _v.head(_MAX_PERSIST_ROWS)
                # MultiIndex columns → 展平
                if isinstance(_slice.columns, __pd.MultiIndex):
                    _slice = _slice.copy()
                    _slice.columns = ['_'.join(str(x) for x in col).strip('_') for col in _slice.columns]
                # 确保列名是字符串（Parquet 要求）
                _slice = _slice.copy()
                _slice.columns = [str(c) for c in _slice.columns]
                _ppath = _os.path.join(_persist_dir, _k + ".parquet")
                _slice.to_parquet(_ppath, engine='pyarrow', index=False)
                if _os.path.getsize(_ppath) <= _MAX_PARQUET_SIZE:
                    _persisted_vars[_k] = _ppath
                    _persist_count += 1
                else:
                    _os.unlink(_ppath)
            # ── Series → Parquet（带元数据标记） ─────────
            elif isinstance(_v, __pd.Series):
                _slice = _v.head(_MAX_PERSIST_ROWS)
                _col_name = str(_slice.name) if _slice.name is not None else "__series__"
                _tmp_df = _slice.to_frame(name=_col_name)
                _table = __pa.Table.from_pandas(_tmp_df, preserve_index=False)
                # 在 schema metadata 中写入类型标记，恢复时可区分 Series 与 DataFrame
                _existing_meta = _table.schema.metadata or {{}}
                _existing_meta[b'__persist_type__'] = b'series'
                _existing_meta[b'__series_name__'] = _col_name.encode('utf-8')
                _table = _table.replace_schema_metadata(_existing_meta)
                _ppath = _os.path.join(_persist_dir, _k + ".parquet")
                __pq.write_table(_table, _ppath)
                if _os.path.getsize(_ppath) <= _MAX_PARQUET_SIZE:
                    _persisted_vars[_k] = _ppath
                    _persist_count += 1
                else:
                    _os.unlink(_ppath)
            # ── numpy ndarray → JSON（体积通常极小） ─────
            elif isinstance(_v, __np.ndarray):
                if _v.size > _MAX_PERSIST_ROWS:
                    _v = __np.array(_v.flat[:_MAX_PERSIST_ROWS])
                _blob = {{
                    "__persist_type__": "ndarray",
                    "data": _v.tolist(),
                    "dtype": str(_v.dtype),
                    "shape": list(_v.shape),
                }}
                _json_str = json.dumps(_blob, ensure_ascii=False, default=str)
                if len(_json_str) <= _MAX_JSON_VALUE_SIZE:
                    _ppath = _os.path.join(_persist_dir, _k + ".json")
                    with open(_ppath, 'w', encoding='utf-8') as _pf:
                        _pf.write(_json_str)
                    _persisted_vars[_k] = _ppath
                    _persist_count += 1
            # ── numpy scalar → JSON ─────────────────────
            elif isinstance(_v, __np.generic):
                _blob = {{
                    "__persist_type__": "numpy_scalar",
                    "value": _v.item(),
                    "dtype": str(_v.dtype),
                }}
                _json_str = json.dumps(_blob, ensure_ascii=False, default=str)
                if len(_json_str) <= _MAX_JSON_VALUE_SIZE:
                    _ppath = _os.path.join(_persist_dir, _k + ".json")
                    with open(_ppath, 'w', encoding='utf-8') as _pf:
                        _pf.write(_json_str)
                    _persisted_vars[_k] = _ppath
                    _persist_count += 1
            # ── Python 基础类型 → JSON ───────────────────
            elif isinstance(_v, (int, float, str, bool, list, dict, tuple, set, type(None))):
                _serializable = list(_v) if isinstance(_v, (tuple, set)) else _v
                _blob = {{"__persist_type__": "value", "value": _serializable}}
                _json_str = json.dumps(_blob, ensure_ascii=False, default=str)
                if len(_json_str) <= _MAX_JSON_VALUE_SIZE:
                    _ppath = _os.path.join(_persist_dir, _k + ".json")
                    with open(_ppath, 'w', encoding='utf-8') as _pf:
                        _pf.write(_json_str)
                    _persisted_vars[_k] = _ppath
                    _persist_count += 1
            # ── 其他类型：跳过 ──────────────────────────
            else:
                continue
        except Exception:
            pass
result = {{
    "success": _error is None,
    "output": _output if _output else None,
    "error": _error,
    "dataframes": _captured_dfs,
    "persisted_vars": _persisted_vars,
    "charts": _captured_charts,
    "maps": _captured_maps,
}}
print(json.dumps(result, ensure_ascii=False))
    """
    return script

async def execute_code_in_sandbox(
    code: str,
    data_var_map: dict[str, str],
    timeout: int = SANDBOX_TOTAL_TIMEOUT,
    capture_dir: str | None = None,
    injected_envs: dict[str, str] | None = None,
    persisted_var_map: dict[str, str] | None = None,  # 上一轮持久化的变量 (.parquet/.json)
) -> dict[str, Any]:
    """
    在子进程中安全执行代码。增加支持心跳机制。
    心跳策略：
    - 监控stdout输出和心跳文件
    - 90秒无任何活动 → 杀进程
    - 2小时总超时 → 硬上限

    Args:
        code: 要执行的 Python 代码
        data_var_map: {变量名: CSV文件绝对路径}
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

    # ── 【新增】从 injected_envs 中分离 allowed_modules ──
    # injected_envs 可能包含一个特殊 key "__allowed_modules__"
    # 它是 JSON 字符串，如 '["pytalos"]'，需要提取出来给沙箱白名单
    # 剩下的 clean_envs 才是真正要注入子进程的环境变量
    extra_modules: list[str] = []
    clean_envs: dict[str, str] | None = injected_envs
    if injected_envs and "__allowed_modules__" in injected_envs:
        import json as _json
        try:
            extra_modules = _json.loads(injected_envs["__allowed_modules__"])
        except (ValueError, TypeError):
            pass
        # 去掉特殊 key，只保留真正的环境变量
        clean_envs = {k: v for k, v in injected_envs.items() if k != "__allowed_modules__"}

    # 创建心跳文件
    heartbeat_file = os.path.join(
        tempfile.gettempdir(),
        f"owl_sandbox_{uuid.uuid4().hex}.heartbeat"
    )

    # ── 构建沙箱脚本（原有位置，增加 extra_modules 参数） ──
    script_content = _build_sandbox_script(code, data_var_map, capture_dir, extra_modules, persisted_var_map, heartbeat_file)
    
    tmp_file = None
    start_time = time.monotonic()
    try:
        tmp_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        )
        tmp_file.write(script_content)
        tmp_file.flush()
        tmp_file.close()
        # 始终构建 sandbox_env 以注入 WAREHOUSE_PATH
        sandbox_env = {}
        # 保留必要的系统路径变量
        for key in ("PATH", "PYTHONPATH", "SYSTEMROOT", "HOME", "LANG", "LC_ALL"):
            if key in os.environ:
                sandbox_env[key] = os.environ[key]
        # 注入 DuckDB 仓库路径
        from app.config import WAREHOUSE_PATH
        sandbox_env["WAREHOUSE_PATH"] = str(WAREHOUSE_PATH)
        # 注入 Skill 环境变量（如 TALOS_USER, TALOS_TOKEN）
        if clean_envs:
            sandbox_env.update(clean_envs)
        # 在子进程中执行
        proc = await asyncio.create_subprocess_exec(
            PYTHON_EXECUTABLE, tmp_file.name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=UPLOADS_DIR,  # 沙箱工作目录
            env=sandbox_env,  # None 时继承父进程环境，有值时使用精简环境
        )

        # ── 心跳监控逻辑 ──────────────────────────────────
        timeout_reason = None
        
        async def monitor_heartbeat():
            """监控心跳文件，超时则杀进程"""
            nonlocal timeout_reason
            last_heartbeat_time = time.monotonic()
            
            while proc.returncode is None:
                await asyncio.sleep(5)
                now = time.monotonic()
                
                # 检查心跳文件
                if os.path.exists(heartbeat_file):
                    try:
                        mtime = os.path.getmtime(heartbeat_file)
                        file_age = now - mtime
                        if file_age < 30:  # 心跳文件30秒内更新过
                            last_heartbeat_time = now
                    except OSError:
                        pass
                
                # 判断超时
                idle_time = now - last_heartbeat_time
                total_time = now - start_time
                
                if idle_time > SANDBOX_IDLE_TIMEOUT:
                    timeout_reason = "idle"
                    proc.kill()
                    return
                
                if total_time > timeout:
                    timeout_reason = "total"
                    proc.kill()
                    return
        
        # 并发执行：communicate + 心跳监控
        monitor_task = asyncio.create_task(monitor_heartbeat())
        
        try:
            # 使用 communicate() 读取输出
            stdout_bytes, stderr_bytes = await proc.communicate()
        finally:
            # 确保监控任务结束
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
        
        elapsed = time.monotonic() - start_time
        
        # 处理超时情况
        if timeout_reason == "idle":
            return {
                "success": False,
                "output": None,
                "error": (
                    f"⏱️ Code execution appears to be stuck "
                    f"(no activity for {SANDBOX_IDLE_TIMEOUT}s). "
                    f"Consider adding print() statements to show progress."
                ),
                "execution_time": elapsed,
                "dataframes": [],
            }
        
        if timeout_reason == "total":
            return {
                "success": False,
                "output": None,
                "error": f"⏱️ Code execution exceeded maximum time limit ({timeout}s)",
                "execution_time": elapsed,
                "dataframes": [],
            }
        
        # 正常结束，解析输出
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
        # 清理心跳文件
        if os.path.exists(heartbeat_file):
            try:
                os.unlink(heartbeat_file)
            except OSError:
                pass