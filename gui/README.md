# Knowledge Graph GUI

React + TypeScript web UI for the knowledge graph API.

## Prerequisites

1. API server running:

```bash
uv run python main.py server
```

Default API port is **5001** (`n8n.port` in `config/config.yaml`).

2. Node.js 18+

## Development

```bash
cd gui
npm install
npm run dev
```

Open http://localhost:5173 — Vite proxies `/api` to the Flask server (default port **5001**).

To use a different API port, set `n8n.port` in `config/config.yaml` and pass `KGS_API_PORT` when starting Vite (or use `./scripts/start-dev.sh`).

TypeScript interfaces in `src/api/types.ts` mirror the API; see [../docs/INFOMODEL.md](../docs/INFOMODEL.md) for the full information model and endpoint mapping.

## Production build

```bash
npm run build
npm run preview
```

Set `VITE_API_BASE=http://127.0.0.1:5001/api/v1` if the UI is not served behind the same origin as the API.

## Screens

| Route | Purpose |
|-------|---------|
| `/` | Dashboard — precheck, jobs, documents, archive |
| `/process` | Upload document, run pipeline, SSE progress |
| `/ontology` | Review and approve ontology proposals |
| `/normalize` | Predicate map scan, review, apply |
| `/benchmark` | Runs / chunks / LLM tables |
