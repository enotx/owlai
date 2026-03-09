#!/bin/bash
# scripts/cleanup-dev.sh

set -e

# 🔥 智能检测项目根目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🧹 Cleaning up Owl development environment..."
echo "📂 Project root: $PROJECT_ROOT"

# 杀死进程
echo "   Stopping processes..."
pkill -f "Owl Data Analyzer" 2>/dev/null || true
pkill -f "sidecar_main.py" 2>/dev/null || true
pkill -f "cargo run" 2>/dev/null || true

# 清理端口文件
PORT_FILE="$HOME/.owl_backend_port"
if [ -f "$PORT_FILE" ]; then
    echo "   Removing port file..."
    rm -f "$PORT_FILE"
fi

# 清理 Cargo 构建产物
TAURI_DIR="$PROJECT_ROOT/frontend/src-tauri"
if [ -d "$TAURI_DIR" ]; then
    echo "   Cleaning cargo build artifacts..."
    cd "$TAURI_DIR"
    cargo clean
fi

echo "✅ Cleanup complete!"
echo ""
echo "💡 You can now run: npm run tauri:dev"