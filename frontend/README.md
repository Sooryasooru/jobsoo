# jobsoo dashboard

React + TypeScript + Tailwind dashboard for the jobsoo Phase 1 backend.

## Run

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # type-check + production build
```

The backend must run on `http://127.0.0.1:8000` (its CORS config allows this
origin). Override with `VITE_API_BASE=http://… npm run dev` if the backend
listens elsewhere.

Features: ingest jobs from Adzuna, browse/search jobs, AI requirement
extraction, deterministic match scores with per-requirement evidence
(all tiers stay visible), candidate profile + original CV upload, truthful
tailored-CV drafts with manual approval and PDF download.
