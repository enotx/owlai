# 🧠 项目深度关联地图

## 1. 目录索引
```text
.
├── .gitignore
├── .python-version
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
│   └── requirements.txt
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
├── README.md
└── structure.txt

19 directories, 57 files
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
subgraph 19["sidebar"]
1A["task-sidebar.tsx"]
end
end
subgraph R["lib"]
S["api.ts"]
11["utils.ts"]
end
subgraph V["stores"]
W["use-task-store.ts"]
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
1A-->S
1A-->11
1A-->W
1A-->K
1A-->M
```

## 3. 后端 Service/Router 调用链
```mermaid
graph TD
  chat --depends on--> schemas
  chat --depends on--> agent
  chat --depends on--> models
  knowledge --calls--> db.delete
  chat --depends on--> database
  agent --depends on--> models
  agent --calls--> write_db.commit
  agent --depends on--> data_processor
  knowledge --depends on--> models
  tasks --depends on--> database
  knowledge --calls--> db.commit
  knowledge --depends on--> schemas
  sandbox --depends on--> code_security
  tasks --calls--> db.add
  main --depends on--> database
  chat --calls--> db.execute
  knowledge --calls--> db.add
  knowledge --calls--> db.execute
  agent --calls--> db.execute
  tasks --depends on--> schemas
  tasks --calls--> db.refresh
  tasks --calls--> db.get
  knowledge --calls--> db.get
  agent --depends on--> sandbox
  execute --depends on--> sandbox
  execute --depends on--> models
  knowledge --depends on--> database
  tasks --calls--> db.commit
  execute --depends on--> schemas
  agent --depends on--> database
  main --depends on--> schemas
  execute --depends on--> database
  agent --calls--> write_db.add
  execute --calls--> db.execute
  knowledge --calls--> db.refresh
  execute --depends on--> data_processor
  models --depends on--> database
  main --depends on--> routers
  agent --calls--> write_db.refresh
  knowledge --depends on--> data_processor
  tasks --depends on--> models
  tasks --calls--> db.execute
  tasks --calls--> db.delete```

