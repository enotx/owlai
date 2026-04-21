# backend/app/services/execution/jupyter/probe.py

"""探针代码生成 — 替代文件系统扫描"""

import textwrap


def build_setup_code() -> str:
    """构建注入远端 kernel 的 helper 函数（首次连接时执行）"""
    return textwrap.dedent("""\
        import os as _os
        import json as _json
        import pandas as pd
        import numpy as np

        # ── 图表捕获 ──────────────────────────────────────
        _captured_charts = []
        _captured_maps = []

        def create_chart(title, chart_type, option):
            def _serialize(obj):
                if isinstance(obj, dict):
                    return {k: _serialize(v) for k, v in obj.items()}
                if isinstance(obj, (list, tuple)):
                    return [_serialize(v) for v in obj]
                if hasattr(obj, 'item'):
                    return obj.item()
                if hasattr(obj, 'tolist'):
                    return obj.tolist()
                if obj is True:
                    return True
                if obj is False:
                    return False
                if obj is None:
                    return None
                if isinstance(obj, (int, float, str)):
                    return obj
                return str(obj)
            _captured_charts.append({
                "title": str(title),
                "chart_type": str(chart_type),
                "option": _serialize(option),
            })
            print(f"[Chart created: {title}]")

        def create_map(title, config):
            def _serialize(obj):
                if isinstance(obj, dict):
                    return {k: _serialize(v) for k, v in obj.items()}
                if isinstance(obj, (list, tuple)):
                    return [_serialize(v) for v in obj]
                if hasattr(obj, 'item'):
                    return obj.item()
                if hasattr(obj, 'tolist'):
                    return obj.tolist()
                return obj
            _captured_maps.append({
                "title": str(title),
                "config": _serialize(config),
            })
            print(f"[Map created: {title}]")

        def getenv(key, default=None):
            return _os.environ.get(key, default)

        # ── Artifact 存储（远端临时目录）──────────────────
        def save_artifact(name, obj):
            import joblib
            _dir = "/tmp/owl_artifacts"
            _os.makedirs(_dir, exist_ok=True)
            safe_name = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in str(name))
            path = _os.path.join(_dir, f"{safe_name}.joblib")
            joblib.dump(obj, path)
            print(f"[Artifact saved: {safe_name}]")

        def load_artifact(name):
            import joblib
            safe_name = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in str(name))
            path = f"/tmp/owl_artifacts/{safe_name}.joblib"
            return joblib.load(path)

        print("__OWL_SETUP_OK__")
    """)


def build_probe_code() -> str:
    """构建探针代码（执行后追加，收集变量/DataFrame/图表信息）"""
    return textwrap.dedent("""\
        import json as _pjson
        import pandas as _ppd
        import numpy as _pnp

        _probe_result = {
            "dataframes": [],
            "charts": _captured_charts.copy() if '_captured_charts' in dir() else [],
            "maps": _captured_maps.copy() if '_captured_maps' in dir() else [],
            "variables": [],
        }

        _SKIP = {'pd', 'np', 'pandas', 'numpy', 'In', 'Out', '_', '__', '___',
                 '_captured_charts', '_captured_maps', 'create_chart', 'create_map',
                 'getenv', 'save_artifact', 'load_artifact', 'get_dataframes',
                 '_pjson', '_ppd', '_pnp', '_probe_result', '_SKIP'}

        for _k, _v in list(globals().items()):
            if _k.startswith('_') or _k in _SKIP:
                continue
            if isinstance(_v, _ppd.DataFrame):
                _cols = [str(c) for c in _v.columns.tolist()[:20]]
                _probe_result["dataframes"].append({
                    "name": _k,
                    "row_count": len(_v),
                    "columns": _cols,
                    "preview_count": min(len(_v), 5),
                })
            elif isinstance(_v, (_ppd.Series, _pnp.ndarray, int, float, str, list, dict)):
                _type_name = type(_v).__name__
                _probe_result["variables"].append({
                    "name": _k,
                    "type": _type_name,
                    "shape": str(getattr(_v, 'shape', '')),
                })

        # 清空已捕获的图表（避免下次重复）
        if '_captured_charts' in dir():
            _captured_charts.clear()
        if '_captured_maps' in dir():
            _captured_maps.clear()

        print("__OWL_PROBE__" + _pjson.dumps(_probe_result, default=str))
    """)