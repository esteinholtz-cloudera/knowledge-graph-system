# Prompt Tuning

Extraction quality depends on two orthogonal axes of prompt configuration:

| Axis | What varies | Config location |
|---|---|---|
| **Per-model** | JSON format enforcement, few-shot examples | `llm.model_settings.<model>.format_strictness / use_few_shot` |
| **Per-domain** | Entity type vocabulary, predicate vocabulary | `domains.<name>.extra_entity_types / extra_predicates` |

At runtime the two are composed into the final prompt by `src/extraction/prompt_builder.py`.

---

## Using domains

```bash
python main.py process input/ZDU_prereqs.txt --domain technical
python main.py process input/Hamlet.txt       --domain literary
python main.py process input/paper.pdf        --domain scientific
python main.py process input/anything.txt     # --domain default (implicit)
```

Built-in domains (defined in `config.yaml`):

| Domain | Extra entity types | Extra predicates |
|---|---|---|
| `technical` | Service, Version, Configuration, Database, API, Error, Module | deprecates, implements, exposes, dependsOn, isCompatibleWith |
| `literary` | Theme, Symbol, CharacterRole, Scene | loves, betrays, opposes, rules, symbolises |
| `scientific` | Drug, Disease, Gene, Pathway, Method, Study | inhibits, activates, correlatesWith, causedBy, treatedBy, expressedIn |

Extra types and predicates are **merged** with the base defaults — they do not replace them.

---

## Adding a custom domain

Add an entry under `domains:` in `config.yaml`:

```yaml
domains:
  legal:
    description: "Legal documents, contracts, regulations"
    extra_entity_types:
      - Clause
      - Obligation
      - Party
      - Jurisdiction
    extra_predicates:
      - obligates
      - prohibits
      - supersedes
      - governedBy
```

Then use it with `--domain legal`.

---

## Model-specific prompt format

### `format_strictness`

Controls how strongly the JSON-only constraint is enforced.

| Level | What's added | When to use |
|---|---|---|
| `low` | "Return ONLY a JSON array — no explanation, no markdown, no preamble." | Good instruction followers (Qwen3, GPT-4) |
| `medium` | + "Start your response with [ and end with ]." | Models that occasionally add preamble (Gemma) |
| `high` | + "Do NOT write any text outside the JSON." | Weaker instruction followers or fine-tuned models |

**Verified output (medium vs low):**

Qwen3 (`format_strictness: low`):
```
Return ONLY a JSON array — no explanation, no markdown, no preamble.
```

Gemma (`format_strictness: medium`):
```
Return ONLY a JSON array — no explanation, no markdown, no preamble.
Start your response with [ and end with ].
```

### `use_few_shot`

When `true`, a single in-domain few-shot example is prepended to the user prompt:

```
Example input: "Marie Curie discovered radium in Paris in 1898."
Example output:
[
  {"entity": "Marie Curie", "type": "Person", "context": "scientist who discovered radium"},
  {"entity": "radium", "type": "Technology", "context": "element discovered by Marie Curie"},
  {"entity": "Paris", "type": "Location", "context": "city where discovery occurred"},
  {"entity": "1898", "type": "Date", "context": "year of discovery"}
]
```

Use for models that struggle to produce the correct JSON schema on first attempt.
Adds ~80 tokens of overhead per chunk — not free, but modest.

### Configuring per model

```yaml
llm:
  format_strictness: low   # global default
  use_few_shot: false
  model_settings:
    qwen3-30b-a3b-instruct-2507-mlx:
      format_strictness: low
      use_few_shot: false
    gemma-4-26b-a4b-it-mlx:
      format_strictness: medium
      use_few_shot: false
    some-small-model:
      format_strictness: high
      use_few_shot: true   # needs the example to produce valid JSON
```

---

## How prompts are assembled

`src/extraction/prompt_builder.py` is the single source of truth.

```
build_entity_prompts(llm_cfg, domain) → (system_prompt, user_template)
build_relationship_prompts(llm_cfg, domain) → (system_prompt, user_template)
```

The system prompt structure:

```
You are an expert at extracting named entities from text.
[Domain context: <description>]                     ← if domain.description set

Extract all meaningful entities.

Return ONLY a JSON array — no explanation, no markdown, no preamble.
[<format_strictness suffix>]                        ← medium/high only
Each element must have:
- "entity": ...
- "type": one of <base types> | <domain extra types>
- "context": ...
```

The user prompt template:

```
[<few-shot example>]                                ← if use_few_shot=True
Text:
{text}

JSON array (no preamble):
```

---

## Test results

Verified combinations (`uv run python -c ...`):

| Model | Domain | Service | Theme | Drug | Markers | Few-shot |
|---|---|---|---|---|---|---|
| qwen3 | default | ✗ | ✗ | ✗ | ✗ | ✗ |
| qwen3 | technical | ✓ | ✗ | ✗ | ✗ | ✗ |
| qwen3 | literary | ✗ | ✓ | ✗ | ✗ | ✗ |
| qwen3 | scientific | ✗ | ✗ | ✓ | ✗ | ✗ |
| gemma | default | ✗ | ✗ | ✗ | ✓ | ✗ |
| gemma | technical | ✓ | ✗ | ✗ | ✓ | ✗ |
| unknown | technical | ✓ | ✗ | ✗ | ✗ | ✗ |

Unknown models fall back to global defaults (`format_strictness: low`, `use_few_shot: false`).

---

## Calibration (future)

Domain vocabulary was seeded manually based on domain knowledge.
The intended long-term workflow:

1. Process a sample corpus with `--domain default`
2. Observe which entity types get `ont:Other` (unrecognised types)
3. Move those types to the appropriate domain's `extra_entity_types`
4. Re-process and compare benchmark metrics (entity yield, `ont:Other` rate)

See `TODO.md` for the automated calibration tool that will close this loop.
