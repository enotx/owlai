# 🦉 Owl - AI Data Analyst

AI 驱动的数据分析工具，通过对话让 AI Agent 分析数据、自动编写 Pandas 代码并得出结论。

## 快速启动

### 1. 后端

``` bash
cd backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 复制配置文件
cp .env.example .env
# 编辑 .env 填入 OPENAI_API_KEY（当前阶段可跳过）

# 启动
uvicorn app.main:app --reload --port 8000
```

### 2. 前端

``` bash
cd frontend
# 安装依赖
npm install
# 安装额外依赖
npm install zustand axios lucide-react
# 初始化 shadcn/ui（如果尚未执行）
npx shadcn@latest init -d
npx shadcn@latest add button card input textarea scroll-area table badge separator
# 启动
npm run dev
```


### 3. 访问
访问 http://localhost:3000