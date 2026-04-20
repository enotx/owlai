# backend/app/services/code_security.py

"""AST 静态分析：在执行前检测危险代码模式"""

import ast
from dataclasses import dataclass


@dataclass
class SecurityCheckResult:
    """安全检查结果"""
    safe: bool
    violations: list[str]


# ── 黑名单 ─────────────────────────────────────────────────
# 禁止 import 的顶级模块
FORBIDDEN_MODULES = frozenset({
    "os", "sys", "subprocess", "shutil", "pathlib",
    "socket", "http", "urllib", "httpx", # 我允许了requests，因为有时需要agent调用某些线上接口
    "ftplib", "smtplib", "ctypes", "multiprocessing",
    "threading", "signal", "importlib", "pkgutil",
    "code", "codeop", "compile", "compileall",
    "pickle", "shelve", "marshal",
    "webbrowser", "antigravity",
    "builtins", "__builtin__",
    "io",           # 防止 open 的替代
    "tempfile",
    "glob", "fnmatch",
    "sqlite3", "dbm",
    "xml", "html",  # XXE 等风险
    "gc", "inspect", "dis", "tracemalloc",
    "resource", "pty", "termios", "tty",
})

# 禁止调用的函数名
FORBIDDEN_CALLS = frozenset({
    "eval", "exec", "compile",
    "open", "input",
    "__import__",
    "locals", "vars",
    "getattr", "setattr", "delattr",
    "breakpoint", "exit", "quit",
    "memoryview",
    "help",  # 可触发 pager
})

# 禁止访问的属性名（用于拦截沙箱逃逸）
FORBIDDEN_ATTRS = frozenset({
    "__subclasses__",
    "__bases__",
    "__mro__",
    "__class__",
    "__globals__",
    "__code__",
    "__closure__",
    "__func__",
    "__self__",
    "__module__",
    "__import__",
    "__loader__",
    "__spec__",
    "__builtins__",
    "__qualname__",
    "gi_frame", "gi_code",  # generator internals
    "f_globals", "f_locals", "f_builtins",  # frame attrs
    "co_code",  # code object
})


class _SecurityVisitor(ast.NodeVisitor):
    """遍历 AST 节点，收集所有安全违规"""

    def __init__(self):
        self.violations: list[str] = []

    # ── import / import from ──────────────────────────────
    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top in FORBIDDEN_MODULES:
                self.violations.append(
                    f"Line {node.lineno}: Forbidden import '{alias.name}'"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            top = node.module.split(".")[0]
            if top in FORBIDDEN_MODULES:
                self.violations.append(
                    f"Line {node.lineno}: Forbidden import from '{node.module}'"
                )
        self.generic_visit(node)

    # ── 函数调用 ──────────────────────────────────────────
    def visit_Call(self, node: ast.Call):
        func_name = self._get_call_name(node.func)
        if func_name in FORBIDDEN_CALLS:
            self.violations.append(
                f"Line {node.lineno}: Forbidden call '{func_name}()'"
            )
        self.generic_visit(node)

    # ── 属性访问 ──────────────────────────────────────────
    def visit_Attribute(self, node: ast.Attribute):
        if node.attr in FORBIDDEN_ATTRS:
            self.violations.append(
                f"Line {node.lineno}: Forbidden attribute access '.{node.attr}'"
            )
        self.generic_visit(node)

    # ── 辅助：提取调用名 ─────────────────────────────────
    @staticmethod
    def _get_call_name(node: ast.expr) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return ""


def check_code_security(code: str) -> SecurityCheckResult:
    """
    对代码进行 AST 静态安全分析。

    Args:
        code: Python 源代码字符串
    Returns:
        SecurityCheckResult: safe=True 表示可放行
    """
    # 1. 先尝试解析 AST（语法错误也要拦截）
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as e:
        return SecurityCheckResult(
            safe=False,
            violations=[f"Syntax error: {e.msg} (line {e.lineno})"],
        )

    # 2. 遍历 AST 收集违规
    visitor = _SecurityVisitor()
    visitor.visit(tree)

    return SecurityCheckResult(
        safe=len(visitor.violations) == 0,
        violations=visitor.violations,
    )