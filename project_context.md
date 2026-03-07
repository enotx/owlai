# 🧠 项目深度关联地图

## 1. 目录索引
```text
.
├── .gitignore
├── backend
│   ├── app
│   │   ├── __init__.py
│   │   ├── database.py
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── routers
│   │   │   ├── __init__.py
│   │   │   ├── chat.py
│   │   │   ├── execute.py
│   │   │   ├── knowledge.py
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
│   │       └── use-task-store.ts
│   └── tsconfig.json
├── llm_scan.py
├── project_context.md
└── README.md

19 directories, 61 files
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
10["message-input.tsx"]
end
subgraph 17["data"]
18["data-panel.tsx"]
end
subgraph 19["settings"]
1A["settings-dialog.tsx"]
1B["providers-view.tsx"]
1C["provider-form.tsx"]
1E["providers-list.tsx"]
end
subgraph 1F["sidebar"]
1G["task-sidebar.tsx"]
end
end
subgraph R["lib"]
S["api.ts"]
11["utils.ts"]
end
subgraph V["stores"]
W["use-task-store.ts"]
1D["use-settings-store.ts"]
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
subgraph T["axios"]
U["index.d.cts"]
end
subgraph X["zustand"]
subgraph Y["esm"]
Z["index.d.mts"]
end
end
subgraph 12["clsx"]
13["clsx.d.mts"]
end
subgraph 14["tailwind-merge"]
subgraph 15["dist"]
16["types.d.ts"]
end
end
end
6-->7
6-->C
6-->F
G-->P
G-->18
G-->1A
G-->1G
G-->S
G-->K
G-->M
P-->Q
P-->10
P-->11
P-->W
P-->W
P-->K
P-->M
Q-->S
Q-->W
Q-->K
Q-->M
S-->U
W-->S
W-->Z
10-->S
10-->S
10-->W
10-->W
10-->K
10-->M
11-->13
11-->16
18-->11
18-->W
18-->K
1A-->1B
1A-->S
1A-->11
1A-->1D
1A-->K
1A-->M
1B-->1C
1B-->1E
1B-->1D
1C-->S
1C-->1D
1C-->K
1C-->M
1D-->Z
1E-->S
1E-->1D
1E-->K
1G-->S
1G-->11
1G-->1D
1G-->W
1G-->K
1G-->M
```

## 3. 后端 Service/Router 调用链
```mermaid
graph TD
  tasks --depends on--> schemas
  llm --depends on--> models
  llm --calls--> db.execute
  knowledge --depends on--> models
  agent --depends on--> sandbox
  knowledge --calls--> db.refresh
  execute --depends on--> sandbox
  knowledge --calls--> db.commit
  chat --depends on--> database
  knowledge --calls--> db.add
  tasks --calls--> db.execute
  llm --depends on--> database
  execute --depends on--> models
  tasks --calls--> db.refresh
  llm --calls--> db.commit
  agent --depends on--> models
  tasks --depends on--> database
  agent --calls--> write_db.commit
  knowledge --depends on--> schemas
  chat --depends on--> agent
  tasks --calls--> db.get
  chat --depends on--> models
  execute --depends on--> data_processor
  models --depends on--> database
  llm --depends on--> schemas
  agent --calls--> write_db.refresh
  knowledge --calls--> db.get
  main --depends on--> database
  knowledge --depends on--> database
  knowledge --depends on--> data_processor
  chat --depends on--> schemas
  knowledge --calls--> db.execute
  execute --depends on--> database
  main --depends on--> routers
  agent --calls--> write_db.add
  sandbox --depends on--> code_security
  main --depends on--> schemas
  agent --depends on--> data_processor
  execute --depends on--> schemas
  llm --calls--> db.refresh
  agent --depends on--> database
  chat --calls--> db.execute
  execute --calls--> db.execute
  llm --calls--> db.add
  tasks --calls--> db.commit
  knowledge --calls--> db.delete
  tasks --calls--> db.delete
  agent --calls--> db.execute
  tasks --depends on--> models
  llm --calls--> db.delete
  tasks --calls--> db.add```

