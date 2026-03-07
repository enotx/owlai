# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///

import os
import ast
import subprocess

# --- 配置 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(BASE_DIR, "backend", "app")
OUTPUT_FILE = "project_context.md"

class BackendDeepAnalyzer(ast.NodeVisitor):
    def __init__(self, current_file):
        self.current_file = current_file
        self.dependencies = set()
        self.calls = []

    def visit_ImportFrom(self, node):
        # 识别从哪个模块导入了什么 (e.g., from app.services import agent)
        if node.module and 'app' in node.module:
            target_module = node.module.split('.')[-1]
            self.dependencies.add(target_module)
        self.generic_visit(node)

    def visit_Call(self, node):
        # 识别函数调用 (e.g., agent_service.run_task())
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                # 记录: 谁 调了 谁的 什么方法
                caller = node.func.value.id
                method = node.func.attr
                self.calls.append(f"{caller}.{method}")
        self.generic_visit(node)

def analyze_backend_deep():
    print("正在进行后端深度 AST 建模...")
    mermaid_lines = []
    
    for root, _, files in os.walk(BACKEND_DIR):
        for file in files:
            if not file.endswith(".py"): continue
            
            file_path = os.path.join(root, file)
            this_mod = file.replace(".py", "")
            
            with open(file_path, "r", encoding="utf-8") as f:
                try:
                    tree = ast.parse(f.read())
                    analyzer = BackendDeepAnalyzer(this_mod)
                    analyzer.visit(tree)
                    
                    # 生成依赖关系 (Mermaid)
                    for dep in analyzer.dependencies:
                        # 排除掉自己引用自己
                        if dep != this_mod:
                            mermaid_lines.append(f"  {this_mod} --depends on--> {dep}")
                    
                    # 如果有具体的 Service 调用，细化它
                    for call in set(analyzer.calls):
                        # 简单过滤：通常 service 或 manager 命名的变量是关键逻辑
                        if any(x in call.lower() for x in ['service', 'agent', 'db', 'repo']):
                            mermaid_lines.append(f"  {this_mod} --calls--> {call}")
                except: continue

    return "graph TD\n" + "\n".join(set(mermaid_lines))

# ... 其他 get_git_tree 和 get_frontend_mermaid 函数保持不变 ...

def main():
    # 执行 Git Tree
    tree_str = subprocess.run("git ls-tree -r --name-only HEAD | tree --fromfile", 
                              shell=True, capture_output=True, text=True).stdout
    
    # 执行前端分析 (需要进入 frontend 目录)
    print("正在分析前端...")
    fe_mermaid = subprocess.run("npx --yes dependency-cruiser src --exclude '^src/components/ui/' --output-type mermaid",
                                 shell=True, capture_output=True, text=True, cwd=os.path.join(BASE_DIR, "frontend")).stdout

    # 执行后端深度分析
    be_mermaid = analyze_backend_deep()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("# 🧠 项目深度关联地图\n\n")
        f.write("## 1. 目录索引\n```text\n" + tree_str + "```\n\n")
        f.write("## 2. 前端组件依赖\n```mermaid\n" + fe_mermaid + "```\n\n")
        f.write("## 3. 后端 Service/Router 调用链\n```mermaid\n" + be_mermaid + "```\n\n")

    print(f"✅ 深度分析完成：{OUTPUT_FILE}")

if __name__ == "__main__":
    main()