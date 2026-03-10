# 🧠 项目深度关联地图

## 1. 目录索引
```text
.
├── .cache
│   └── python-standalone
│       └── cpython-3.12.8+20241219-aarch64-apple-darwin-install_only.tar.gz
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
│   │   ├── contexts
│   │   │   └── backend-context.tsx
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
│   │   ├── Cargo.lock
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
├── README.md
└── scripts
    ├── buidl-sidecar.ps1
    ├── build-sidecar.sh
    ├── cleanup-dev.ps1
    └── cleanup-dev.sh

28 directories, 100 files
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
R["page.tsx"]
end
subgraph G["contexts"]
H["backend-context.tsx"]
end
subgraph K["lib"]
L["api.ts"]
16["utils.ts"]
end
subgraph W["components"]
subgraph X["chat"]
Y["chat-area.tsx"]
Z["knowledge-zone.tsx"]
15["message-input.tsx"]
end
subgraph 1C["data"]
1D["data-panel.tsx"]
end
subgraph 1E["settings"]
1F["settings-dialog.tsx"]
1G["agents-view.tsx"]
1I["providers-view.tsx"]
1J["provider-form.tsx"]
1K["providers-list.tsx"]
end
subgraph 1L["sidebar"]
1M["task-sidebar.tsx"]
end
end
subgraph 10["stores"]
11["use-task-store.ts"]
1H["use-settings-store.ts"]
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
subgraph I["react"]
J["index.js"]
end
subgraph M["@tauri-apps"]
subgraph N["api"]
O["core.js"]
end
end
subgraph P["axios"]
Q["index.d.cts"]
end
subgraph S["lucide-react"]
subgraph T["dist"]
subgraph U["cjs"]
V["lucide-react.js"]
end
end
end
subgraph 12["zustand"]
subgraph 13["esm"]
14["index.d.mts"]
end
end
subgraph 17["clsx"]
18["clsx.d.mts"]
end
subgraph 19["tailwind-merge"]
subgraph 1A["dist"]
1B["types.d.ts"]
end
end
end
6-->7
6-->H
6-->C
6-->F
H-->L
H-->J
L-->O
L-->Q
R-->Y
R-->1D
R-->1F
R-->1M
R-->H
R-->L
R-->V
R-->J
Y-->Z
Y-->15
Y-->16
Y-->11
Y-->11
Y-->V
Y-->J
Z-->L
Z-->11
Z-->V
Z-->J
11-->L
11-->14
15-->L
15-->L
15-->11
15-->11
15-->V
15-->J
16-->18
16-->1B
1D-->16
1D-->11
1D-->V
1F-->1G
1F-->1I
1F-->L
1F-->16
1F-->1H
1F-->V
1F-->J
1G-->L
1G-->1H
1G-->J
1H-->14
1I-->1J
1I-->1K
1I-->1H
1J-->L
1J-->1H
1J-->V
1J-->J
1K-->L
1K-->1H
1K-->V
1M-->H
1M-->L
1M-->16
1M-->1H
1M-->11
1M-->V
1M-->J
```

## 3. 后端 Service/Router 调用链
```mermaid
graph TD
  chat --depends on--> schemas
  main --depends on--> schemas
  agent --calls--> write_db.commit
  agent --depends on--> database
  tasks --depends on--> database
  execute --depends on--> database
  agent --depends on--> config
  database --depends on--> config
  chat --depends on--> config
  knowledge --depends on--> config
  llm --depends on--> models
  knowledge --calls--> db.execute
  chat --calls--> db.execute
  llm --calls--> db.commit
  tasks --depends on--> schemas
  execute --calls--> db.execute
  tasks --calls--> db.execute
  llm --depends on--> schemas
  sandbox --depends on--> config
  knowledge --calls--> db.delete
  execute --depends on--> schemas
  llm --calls--> db.refresh
  models --depends on--> database
  execute --depends on--> data_processor
  knowledge --depends on--> schemas
  agent --depends on--> sandbox
  execute --depends on--> sandbox
  llm --depends on--> database
  agent --calls--> write_db.add
  llm --calls--> db.add
  tasks --calls--> db.delete
  chat --depends on--> models
  execute --depends on--> models
  chat --depends on--> agent
  knowledge --calls--> db.commit
  agent --calls--> db.execute
  agent --depends on--> data_processor
  knowledge --calls--> db.get
  sandbox --depends on--> code_security
  llm --calls--> db.execute
  knowledge --depends on--> database
  chat --depends on--> database
  knowledge --calls--> db.add
  main --depends on--> database
  agent --calls--> write_db.refresh
  tasks --calls--> db.refresh
  knowledge --depends on--> models
  main --depends on--> config
  tasks --calls--> db.commit
  tasks --depends on--> models
  knowledge --calls--> db.refresh
  knowledge --depends on--> data_processor
  tasks --calls--> db.add
  agent --depends on--> models
  llm --calls--> db.delete
  tasks --calls--> db.get
  main --depends on--> routers```

