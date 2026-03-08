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
│   └── tsconfig.json
├── llm_scan.py
├── project_context.md
└── README.md

20 directories, 68 files
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
1B["agents-view.tsx"]
1D["providers-view.tsx"]
1E["provider-form.tsx"]
1F["providers-list.tsx"]
end
subgraph 1G["sidebar"]
1H["task-sidebar.tsx"]
end
end
subgraph R["lib"]
S["api.ts"]
11["utils.ts"]
end
subgraph V["stores"]
W["use-task-store.ts"]
1C["use-settings-store.ts"]
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
G-->1H
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
1A-->1D
1A-->S
1A-->11
1A-->1C
1A-->K
1A-->M
1B-->S
1B-->1C
1B-->M
1C-->Z
1D-->1E
1D-->1F
1D-->1C
1E-->S
1E-->1C
1E-->K
1E-->M
1F-->S
1F-->1C
1F-->K
1H-->S
1H-->11
1H-->1C
1H-->W
1H-->K
1H-->M
```

## 3. 后端 Service/Router 调用链
```mermaid
graph TD
  agent --depends on--> database
  knowledge --calls--> db.refresh
  execute --depends on--> sandbox
  tasks --calls--> db.execute
  llm --calls--> db.add
  sandbox --depends on--> code_security
  tasks --depends on--> models
  llm --calls--> db.refresh
  tasks --depends on--> schemas
  knowledge --depends on--> models
  llm --calls--> db.delete
  agent --calls--> write_db.refresh
  tasks --calls--> db.delete
  knowledge --calls--> db.delete
  execute --depends on--> data_processor
  tasks --calls--> db.add
  knowledge --calls--> db.commit
  main --depends on--> schemas
  chat --depends on--> database
  chat --depends on--> schemas
  tasks --calls--> db.commit
  llm --depends on--> models
  knowledge --calls--> db.add
  tasks --calls--> db.refresh
  chat --calls--> db.execute
  knowledge --calls--> db.execute
  main --depends on--> database
  main --depends on--> routers
  agent --depends on--> models
  agent --depends on--> data_processor
  execute --depends on--> schemas
  llm --calls--> db.execute
  agent --calls--> db.execute
  execute --calls--> db.execute
  tasks --calls--> db.get
  knowledge --calls--> db.get
  knowledge --depends on--> data_processor
  execute --depends on--> database
  llm --depends on--> database
  chat --depends on--> agent
  knowledge --depends on--> database
  agent --depends on--> sandbox
  llm --depends on--> schemas
  agent --calls--> write_db.commit
  tasks --depends on--> database
  agent --calls--> write_db.add
  chat --depends on--> models
  llm --calls--> db.commit
  execute --depends on--> models
  models --depends on--> database
  knowledge --depends on--> schemas```

