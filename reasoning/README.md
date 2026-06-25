# Reasoning

Downstream bounded context: reliable answers over **verified** graph facts and authored **Rules**.

| Doc | Purpose |
|-----|---------|
| [CONTEXT.md](CONTEXT.md) | Glossary (Reasoning vocabulary only) |
| [docs/adr/](docs/adr/) | Architecture decision records |
| [../CONTEXT-MAP.md](../CONTEXT-MAP.md) | Boundary with parent Ingestion + artifact contract |

**Code layout (planned):** `reasoning/src/`, `reasoning/data/` (verified TTL). Do not import parent `src/`
internals — consume published artifacts only (see CONTEXT-MAP).
