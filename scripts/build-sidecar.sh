#!/bin/bash
# 路径: scripts/build-sidecar.sh
set -e

# 🔥 智能检测项目根目录
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

echo "📂 Project root: $PROJECT_ROOT"

# 目标目录改为项目根目录
DEST_DIR="python_env"
PYTHON_VERSION="3.12.8"
BUILD_DATE="20241219"

# 检测平台
detect_platform() {
    local os=$(uname -s)
    local arch=$(uname -m)
    
    case "$os" in
        Darwin)
            if [ "$arch" = "arm64" ]; then
                echo "aarch64-apple-darwin"
            else
                echo "x86_64-apple-darwin"
            fi
            ;;
        Linux)
            if [ "$arch" = "aarch64" ]; then
                echo "aarch64-unknown-linux-gnu"
            else
                echo "x86_64-unknown-linux-gnu"
            fi
            ;;
        MINGW*|MSYS*|CYGWIN*)
            echo "x86_64-pc-windows-msvc-shared"
            ;;
        *)
            echo "Unsupported OS: $os" >&2
            exit 1
            ;;
    esac
}

PLATFORM=$(detect_platform)
echo "🔍 Detected platform: $PLATFORM"

# 构建下载 URL
PYTHON_ARCHIVE="cpython-${PYTHON_VERSION}+${BUILD_DATE}-${PLATFORM}-install_only.tar.gz"
DOWNLOAD_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${BUILD_DATE}/${PYTHON_ARCHIVE}"

echo "🔨 Preparing portable Python environment..."
rm -rf "$DEST_DIR"
mkdir -p "$DEST_DIR"

# 下载 Python Standalone
CACHE_DIR=".cache/python-standalone"
mkdir -p "$CACHE_DIR"

if [ ! -f "$CACHE_DIR/$PYTHON_ARCHIVE" ]; then
    echo "📥 Downloading Python Standalone from $DOWNLOAD_URL"
    curl -L -o "$CACHE_DIR/$PYTHON_ARCHIVE" "$DOWNLOAD_URL"
else
    echo "✅ Using cached Python Standalone"
fi

# 解压
echo "📦 Extracting Python runtime..."
tar -xzf "$CACHE_DIR/$PYTHON_ARCHIVE" -C "$DEST_DIR"

# 确定 Python 和 pip 路径
if [[ "$PLATFORM" == *"windows"* ]]; then
    PYTHON_EXE="$DEST_DIR/python/python.exe"
    PIP_EXE="$DEST_DIR/python/Scripts/pip.exe"
else
    PYTHON_EXE="$DEST_DIR/python/bin/python3"
    PIP_EXE="$DEST_DIR/python/bin/pip3"
fi

# 验证 Python
echo "🐍 Python version:"
"$PYTHON_EXE" --version

# 升级 pip
echo "📦 Upgrading pip..."
"$PYTHON_EXE" -m pip install --upgrade pip

# 安装依赖（修改这里，显式指定 vendor 目录）
echo "📦 Installing dependencies..."
"$PIP_EXE" install --find-links="$PROJECT_ROOT/backend/vendor" -r backend/requirements.txt

# 复制后端代码
echo "📋 Copying backend code..."
cp -r backend/app "$DEST_DIR/app"
cp backend/sidecar_main.py "$DEST_DIR/sidecar_main.py"

# 生成 runtime manifest
echo "📝 Creating runtime manifest..."
if [[ "$PLATFORM" == *"windows"* ]]; then
    RUNTIME_PYTHON="python/python.exe"
else
    RUNTIME_PYTHON="python/bin/python3"
fi
cat > "$DEST_DIR/runtime_manifest.json" <<EOF
{
  "runtime_python": "$RUNTIME_PYTHON",
  "platform": "$PLATFORM",
  "python_version": "$PYTHON_VERSION",
  "build_date": "$BUILD_DATE"
}
EOF

# 清理缓存
echo "🧹 Cleaning up..."
find "$DEST_DIR" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$DEST_DIR" -type f -name "*.pyc" -delete
find "$DEST_DIR" -type f -name "*.pyo" -delete

echo "✅ Portable Python environment ready at $PROJECT_ROOT/$DEST_DIR"
echo "📊 Size: $(du -sh "$DEST_DIR" | cut -f1)"