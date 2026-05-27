# Atlas LMS — Local AI Assistant + Map Generator

## Folder Structure

```
atlas-lms/
├── START.sh                  ← Run this to start everything
├── README.md                 ← This file
│
├── backend/                  ← Flask Python server
│   ├── app.py                ← Main entry point — run this
│   ├── requirements.txt      ← Python packages
│   ├── routes/
│   │   ├── chat_routes.py    ← Chat + map mode logic
│   │   ├── map_routes.py     ← CSV upload, map download
│   │   ├── project_routes.py ← Project management
│   │   ├── study_routes.py   ← MCQ, notes, assignments
│   │   └── file_routes.py    ← File upload/download
│   └── utils/
│       ├── llm.py            ← Ollama/qwen2.5 connection
│       ├── map_generator.py  ← Choropleth map code writer
│       ├── storage.py        ← JSON file helpers
│       └── csv_handler.py    ← CSV parsing
│
├── frontend/                 ← Browser UI
│   ├── index.html            ← Main page
│   ├── style.css             ← Dark theme styling
│   └── script.js             ← All UI logic
│
└── storage/                  ← Auto-created, all data saved here
    ├── chats/                ← Chat sessions (.json)
    ├── maps/                 ← Generated map images
    ├── history/              ← Map archive + thumbnails
    ├── projects/             ← Project data
    ├── notes/                ← Study notes
    ├── files/                ← Uploaded files
    └── uploads/              ← CSV files
```

## How to Run

### Option 1 — One command (easiest)
```bash
bash START.sh
```

### Option 2 — Manual (two terminals)

**Terminal 1 — Backend:**
```bash
cd atlas-lms/backend
pip3 install flask flask-cors requests geopandas matplotlib pandas numpy shapely
python3 app.py
```

**Terminal 2 — Frontend:**
```bash
cd atlas-lms/frontend
python3 -m http.server 3000
```

Then open Chrome at: http://localhost:3000

## Features
- ChatGPT-like AI chat (qwen2.5:7b via Ollama)
- Auto choropleth map generation from CSV
- Projects, Notes, Study Tools
- MCQ Generator, Assignment Generator
- Pomodoro Timer
- Dark/Light theme
- Multi-chat sessions saved locally
- Map download (PNG/JPG/PDF)


http://[::]:3000/atlas-lms/frontend/
python3 app.py

python3 -m http.server 3000


ugrades


CFix 1 — Vision model not found (image description failing)
Root cause: image_processor.py tried qwen2.5-vl:7b (with dash) but your Ollama has qwen2.5vl:7b (without dash). Both are the same model with different tag names.
Added ALL variants to try list:
qwen2.5vl:7b     ← your installed model (no dash) — now tried FIRST
qwen2.5-vl:7b    ← official name
qwen2.5-vl:latest
qwen2.5vl:latest
llava:7b → llava:latest → llava → moondream
Also fixed: stops trying if Ollama isn't running at all (was hanging on timeouts).


Fix 2 — Dataset "Map it" badge not clearing after map generated
hideDatasetBadge() now called immediately after appendMsgWithMap() in sendMsg.


Fix 3 — Paste/drag image directly into message box

Ctrl+V — paste any image or file directly into chat textarea → attaches it
Drag any file onto textarea → attaches it
Works for all supported types: images, PDF, Excel, Word, CSV, text
Textarea shows blue dashed border while dragging over it
Uses same attachment flow as pin icon — file goes WITH your message

Fix 4 — Project chats: click to open like ChatGPT

Whole chat row is now clickable — no more separate "Open" button
Remove button (✕) appears on hover only (like ChatGPT)
"+ New Chat in Project" button appears at top of chats list
Empty state also has "+ Start New Chat" button
Project docs automatically shared with ALL chats in project (already wired via build_project_context → activeProjectId)
Atlas lms fixed v3ZIP Open in Archive UtilitySonnet 4.6 Adaptive