# 🦉 owl.ai

An AI-powered data analysis platform — think Jupyter, but conversational. Throw in your data and business context, ask questions in plain language, and Owl's multi-agent system writes Python code, runs it in a sandbox, and delivers insights with visualizations. When you nail an analysis, crystallize it into reusable Scripts or SOPs for repeated execution.

**Your data never leaves your machine.** No cloud services, no telemetry. The LLM only helps write code — it never sees your full dataset.

![License](https://img.shields.io/badge/license-GPLv3-blue)

## Features

- **Conversational Analysis** — Describe what you need in natural language. Owl's agents write and execute Python in a sandboxed environment, producing results and ECharts visualizations.
- **Plan Mode** — Like a coding agent: clarifies requirements, confirms metrics definitions, validates data completeness before diving into analysis.
- **Flow-to-Asset** — Successful analyses can be distilled into reusable **Scripts** (deterministic Python, no LLM at runtime) or **SOPs** (structured procedures the LLM follows for repeatable reasoning tasks). Export to Markdown or `.ipynb` anytime.
- **Built-in DuckDB** — Ships with DuckDB as a personal data lakehouse. Handles larger-than-memory datasets on a single machine and serves as long-term analytical storage.
- **Remote Jupyter** — Connect to remote Jupyter environments (e.g. AutoDL GPU instances) for heavy computation or model training.
- **Derived Data Sources** — Materialize intermediate results with attached Pipelines, so downstream tasks can reference cleaned/transformed data directly.
- **Routine Scheduling** — Pin any Script or SOP to a cron trigger (APScheduler) for automated, recurring execution.
- **Skill System** — Extend agent capabilities with Markdown-based knowledge documents that teach agents how to use specific data sources or APIs.
- **Privacy First** — Fully self-hosted. Runs as a local server or a Tauri desktop app with a bundled Portable Python runtime and common data-science libraries.

## Quick Start

### Prerequisites

- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [Node.js](https://nodejs.org/) >= 18
- An LLM provider API key (OpenAI, Anthropic, or any OpenAI-compatible endpoint)

### Development

```bash
# Clone
git clone https://github.com/enotx/owlai.git
cd owlai

# Backend
cd backend
uv sync
uv run dev          # Starts FastAPI dev server with hot-reload

# Frontend (in another terminal)
cd frontend
npm install
npm run dev         # Starts Next.js dev server
```

The frontend proxies API requests to the backend automatically. Open `http://localhost:3000`.

### Production (Self-Hosted)

```bash
# Backend
cd backend
uv sync --frozen
uv run build        # Bundles for production

# Frontend
cd frontend
npm ci
npm run build
npm run start
```

### Desktop App (Tauri)

The desktop build bundles a Portable Python runtime with pre-installed data-science libraries — no system Python required.

```bash
cd frontend

# macOS
../scripts/build-sidecar.sh
npm run tauri build

# Windows
..\scripts\build-sidecar.ps1
npm run tauri build
```

Pre-built binaries are available on the [Releases](https://github.com/enotx/owlai/releases) page for macOS and Windows.

## Configuration

owl.ai is configured through the in-app Settings UI:

| Section | What you configure |
|---|---|
| **Providers** | LLM provider endpoints and API keys |
| **Agents** | Which model each agent (Plan / Analyst / TaskManager) uses |
| **Runtimes** | Local sandbox or remote Jupyter connection |
| **Skills** | Custom knowledge documents for domain-specific analysis |
| **Interface** | Language, theme (including Eva Unit-01 / Unit-02 🤖) |

All configuration is stored locally in SQLite — nothing leaves your machine.

## App Modes

| Mode | `APP_MODE` | Description |
|---|---|---|
| Development | `dev` | Hot-reload for both frontend and backend |
| Desktop | `desktop` | Tauri + Sidecar with bundled Portable Python |

## Tech Stack

| Layer | Stack |
|---|---|
| Frontend | Next.js 16, TypeScript, Tailwind CSS, shadcn/ui, Zustand, dnd-kit |
| Desktop | Tauri v2 (Rust) |
| Backend | FastAPI, Python 3.12, SQLAlchemy (async), Pydantic |
| Database | SQLite (metadata), DuckDB (analytical warehouse) |
| Scheduling | APScheduler |
| Package Mgmt | uv (Python), npm (Node.js) |

## Project Structure

```
owlai/
├── backend/
│   ├── app/
│   │   ├── models.py          # SQLAlchemy models
│   │   ├── schemas.py         # Pydantic schemas
│   │   ├── routers/           # FastAPI route handlers
│   │   ├── services/
│   │   │   ├── agents/        # PlanAgent, AnalystAgent, TaskManagerAgent, Orchestrator
│   │   │   ├── execution/     # Sandbox, Jupyter backend, runtime resolver
│   │   │   ├── sandbox.py     # Secure code execution
│   │   │   ├── warehouse.py   # DuckDB warehouse operations
│   │   │   └── ...
│   │   ├── prompts/           # Agent system prompts & fragments
│   │   └── tools/             # Tool definitions & registry
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── app/               # Next.js App Router pages
│   │   ├── components/        # React components (chat, data, settings, ...)
│   │   ├── stores/            # Zustand stores
│   │   ├── contexts/          # React contexts
│   │   └── locales/           # i18n translations
│   └── src-tauri/             # Tauri desktop shell (Rust)
└── scripts/                   # Build & cleanup helpers
```

## Security

- All user code runs in a **sandboxed environment** with dangerous modules (`os`, `sys`, `subprocess`, etc.) blocked at import time.
- Execution has **timeout and memory limits**.
- Online data source queries are **read-only**, capped at 10,000 rows, with parameterized queries to prevent SQL injection.
- LLM agents **never receive raw data** — they only write code that the sandbox executes against local files.

## License

This project is licensed under the [GNU General Public License v3.0].