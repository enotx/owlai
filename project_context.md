# 🧠 项目深度关联地图

## 1. 目录索引
```text
.
├── .gitignore
├── backend
│   ├── app
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── routers
│   │   │   ├── __init__.py
│   │   │   ├── chat.py
│   │   │   ├── execute.py
│   │   │   ├── knowledge.py
│   │   │   ├── llm.py
│   │   │   └── tasks.py
│   │   ├── schemas.py
│   │   └── services
│   │       ├── __init__.py
│   │       ├── agent.py
│   │       ├── code_security.py
│   │       ├── data_processor.py
│   │       └── sandbox.py
│   ├── main.py
│   ├── pyproject.toml
│   ├── README.md
│   ├── requirements.txt
│   ├── run.py
│   ├── sidecar_main.py
│   └── uv.lock
├── frontend
│   ├── components.json
│   ├── eslint.config.mjs
│   ├── next-env.d.ts
│   ├── next.config.ts
│   ├── package-lock.json
│   ├── package.json
│   ├── postcss.config.mjs
│   ├── public
│   │   ├── file.svg
│   │   ├── globe.svg
│   │   ├── next.svg
│   │   ├── vercel.svg
│   │   └── window.svg
│   ├── src
│   │   ├── app
│   │   │   ├── api
│   │   │   │   └── chat
│   │   │   │       └── stream
│   │   │   │           └── route.ts
│   │   │   ├── favicon.ico
│   │   │   ├── globals.css
│   │   │   ├── layout.tsx
│   │   │   └── page.tsx
│   │   ├── components
│   │   │   ├── chat
│   │   │   │   ├── chat-area.tsx
│   │   │   │   ├── knowledge-zone.tsx
│   │   │   │   └── message-input.tsx
│   │   │   ├── data
│   │   │   │   └── data-panel.tsx
│   │   │   ├── settings
│   │   │   │   ├── agents-view.tsx
│   │   │   │   ├── provider-form.tsx
│   │   │   │   ├── providers-list.tsx
│   │   │   │   ├── providers-view.tsx
│   │   │   │   └── settings-dialog.tsx
│   │   │   ├── sidebar
│   │   │   │   └── task-sidebar.tsx
│   │   │   └── ui
│   │   │       ├── badge.tsx
│   │   │       ├── button.tsx
│   │   │       ├── card.tsx
│   │   │       ├── dialog.tsx
│   │   │       ├── input.tsx
│   │   │       ├── scroll-area.tsx
│   │   │       ├── select.tsx
│   │   │       ├── separator.tsx
│   │   │       ├── table.tsx
│   │   │       ├── textarea.tsx
│   │   │       └── tooltip.tsx
│   │   ├── lib
│   │   │   ├── api.ts
│   │   │   └── utils.ts
│   │   └── stores
│   │       ├── use-settings-store.ts
│   │       └── use-task-store.ts
│   ├── src-tauri
│   │   ├── build.rs
│   │   ├── capabilities
│   │   │   └── default.json
│   │   ├── Cargo.toml
│   │   ├── icons
│   │   │   ├── 128x128.png
│   │   │   ├── 128x128@2x.png
│   │   │   ├── 32x32.png
│   │   │   ├── icon.icns
│   │   │   ├── icon.ico
│   │   │   ├── icon.png
│   │   │   ├── Square107x107Logo.png
│   │   │   ├── Square142x142Logo.png
│   │   │   ├── Square150x150Logo.png
│   │   │   ├── Square284x284Logo.png
│   │   │   ├── Square30x30Logo.png
│   │   │   ├── Square310x310Logo.png
│   │   │   ├── Square44x44Logo.png
│   │   │   ├── Square71x71Logo.png
│   │   │   ├── Square89x89Logo.png
│   │   │   └── StoreLogo.png
│   │   ├── src
│   │   │   ├── lib.rs
│   │   │   └── main.rs
│   │   └── tauri.conf.json
│   └── tsconfig.json
├── llm_scan.py
├── project_context.md
└── README.md

24 directories, 93 files
```

## 2. 前端组件依赖
```mermaid
flowchart LR

subgraph 0["src"]
subgraph 1["app"]
subgraph 2["api"]
subgraph 3["chat"]
subgraph 4["stream"]
5["route.ts"]
end
end
end
6["layout.tsx"]
7["globals.css"]
G["page.tsx"]
end
subgraph N["components"]
subgraph O["chat"]
P["chat-area.tsx"]
Q["knowledge-zone.tsx"]
13["message-input.tsx"]
end
subgraph 1A["data"]
1B["data-panel.tsx"]
end
subgraph 1C["settings"]
1D["settings-dialog.tsx"]
1E["agents-view.tsx"]
1G["providers-view.tsx"]
1H["provider-form.tsx"]
1I["providers-list.tsx"]
end
subgraph 1J["sidebar"]
1K["task-sidebar.tsx"]
end
end
subgraph R["lib"]
S["api.ts"]
14["utils.ts"]
end
subgraph Y["stores"]
Z["use-task-store.ts"]
1F["use-settings-store.ts"]
end
end
subgraph 8["node_modules"]
subgraph 9["next"]
subgraph A["dist"]
subgraph B["server"]
C["next.js"]
end
end
subgraph D["font"]
subgraph E["google"]
F["index.js"]
end
end
end
subgraph H["lucide-react"]
subgraph I["dist"]
subgraph J["cjs"]
K["lucide-react.js"]
end
end
end
subgraph L["react"]
M["index.js"]
end
subgraph T["@tauri-apps"]
subgraph U["api"]
V["core.js"]
end
end
subgraph W["axios"]
X["index.d.cts"]
end
subgraph 10["zustand"]
subgraph 11["esm"]
12["index.d.mts"]
end
end
subgraph 15["clsx"]
16["clsx.d.mts"]
end
subgraph 17["tailwind-merge"]
subgraph 18["dist"]
19["types.d.ts"]
end
end
end
6-->7
6-->C
6-->F
G-->P
G-->1B
G-->1D
G-->1K
G-->S
G-->K
G-->M
P-->Q
P-->13
P-->14
P-->Z
P-->Z
P-->K
P-->M
Q-->S
Q-->Z
Q-->K
Q-->M
S-->V
S-->X
Z-->S
Z-->12
13-->S
13-->S
13-->Z
13-->Z
13-->K
13-->M
14-->16
14-->19
1B-->14
1B-->Z
1B-->K
1D-->1E
1D-->1G
1D-->S
1D-->14
1D-->1F
1D-->K
1D-->M
1E-->S
1E-->1F
1E-->M
1F-->12
1G-->1H
1G-->1I
1G-->1F
1H-->S
1H-->1F
1H-->K
1H-->M
1I-->S
1I-->1F
1I-->K
1K-->S
1K-->14
1K-->1F
1K-->Z
1K-->K
1K-->M
```

## 3. 后端 Service/Router 调用链
```mermaid
graph TD
  execute --depends on--> schemas
  execute --calls--> db.execute
  tasks --depends on--> models
  knowledge --calls--> db.execute
  tasks --depends on--> database
  main --depends on--> schemas
  chat --depends on--> agent
  agent --depends on--> database
  llm --calls--> db.execute
  main --depends on--> database
  llm --depends on--> models
  execute --depends on--> models
  agent --calls--> write_db.add
  llm --depends on--> schemas
  llm --calls--> db.commit
  tasks --depends on--> schemas
  tasks --calls--> db.delete
  tasks --calls--> db.refresh
  main --depends on--> routers
  execute --depends on--> data_processor
  database --depends on--> config
  sandbox --depends on--> code_security
  llm --calls--> db.add
  chat --depends on--> schemas
  execute --depends on--> sandbox
  agent --calls--> write_db.refresh
  chat --depends on--> models
  main --depends on--> config
  knowledge --calls--> db.get
  agent --depends on--> sandbox
  llm --depends on--> database
  agent --depends on--> models
  knowledge --depends on--> config
  knowledge --calls--> db.delete
  agent --calls--> db.execute
  knowledge --depends on--> schemas
  agent --depends on--> config
  tasks --calls--> db.get
  knowledge --depends on--> database
  sandbox --depends on--> config
  knowledge --calls--> db.refresh
  chat --calls--> db.execute
  knowledge --depends on--> data_processor
  chat --depends on--> database
  llm --calls--> db.delete
  knowledge --depends on--> models
  models --depends on--> database
  tasks --calls--> db.commit
  knowledge --calls--> db.add
  agent --calls--> write_db.commit
  tasks --calls--> db.add
  llm --calls--> db.refresh
  knowledge --calls--> db.commit
  execute --depends on--> database
  agent --depends on--> data_processor
  tasks --calls--> db.execute```

