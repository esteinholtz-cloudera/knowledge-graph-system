# Extraction prompts

Fully-resolved prompt instances for entity and relationship extraction.

## Layout

```
prompts/
  _default/                    # fallback when no model-specific prompts exist
    default/
      entity.system.txt
      entity.user.prefix.txt
      entity.user.suffix.txt
      relationship.system.txt
      relationship.user.prefix.txt
      relationship.user.suffix.txt
    technical/
      ...
  qwen3-30b-a3b-instruct-2507-mlx/
    technical/
      ...
```

Each file is **concrete text** — types, few-shot examples, format rules, and domain
guidance are baked in. Edit these files directly; there are no config placeholders.

At extraction time the pipeline reads files for `{model}/{domain}` and only inserts
the document chunk (and entity list for relationship extraction) between the user
prefix and suffix.

## Resolution order

1. `prompts/{model}/{domain}/`
2. `prompts/{model}/default/`
3. `prompts/_default/{domain}/`
4. `prompts/_default/default/`
5. Built-in defaults from `prompt_builder.py` (if nothing on disk)

## Workflow

1. **Generate** instances from built-in templates + `config.yaml`:
   ```bash
   python main.py prompts regenerate --all
   python main.py prompts regenerate --model qwen3-30b-a3b-instruct-2507-mlx --domain technical
   ```
2. **Edit** the `.txt` files for that model and domain.
3. **Run** extraction — the loaded model name selects the prompt directory.

Re-run regenerate with `--force` to reset files from templates (overwrites edits).

## List on disk

```bash
python main.py prompts list
python main.py prompts list --model qwen3-30b-a3b-instruct-2507-mlx
```

## User prompt assembly

| Pass | Assembly |
|------|----------|
| Entity | `entity.user.prefix.txt` + document chunk + `entity.user.suffix.txt` |
| Relationship | `relationship.user.prefix.txt` + chunk + `\n\nEntities: ` + entity list + `relationship.user.suffix.txt` |

The entity-list separator is fixed in code; everything else lives in the files.
