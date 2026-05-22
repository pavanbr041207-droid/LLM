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
 
cd atlas-lms/frontend
python3 -m http.server 3000