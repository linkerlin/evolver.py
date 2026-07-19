# Skill-to-Recipe Quickstart

> Compose Agent Skills (SKILL.md files) into GEP **Recipes** — structured evolution plans the Hub can distribute and execute.

## Prerequisites

- Python 3.12+ and `uv` installed
- One or more skill directories containing `SKILL.md` files
- Understanding of the GEP Recipe format

## 1. What is a Recipe?

A **Recipe** is a composable evolution plan that bundles multiple Genes into a structured pipeline. It's the bridge between human-authored Agent Skills and machine-executable GEP mutations.

```
SKILL.md files              GEP Recipe                Evolution Cycle
     │                          │                          │
     ├─ skill: triage ─────────┤                          │
     ├─ skill: verify ─────────┤                          │
     └─ skill: deploy ─────────┤                          │
                                │                          │
                                ├─ Step 1: gene_triage ───→ Run
                                ├─ Step 2: gene_verify ───→ Run
                                └─ Step 3: gene_deploy ───→ Run
```

## 2. Compose a recipe from skills

```bash
# Compose from skill directories
uv run evolver skill2recipe ./skills/triage ./skills/verify

# Compose with output to a file
uv run evolver skill2recipe ./skills/triage ./skills/verify > my-recipe.json

# Compose all skills in a directory
uv run evolver skill2recipe ./skills/*
```

### What happens during composition

1. Each SKILL.md is parsed and its content extracted
2. Genes are generated from the skill content (via LLM if needed)
3. Genes are validated against the GEP schema
4. A recipe manifest is assembled with ordered pipeline steps
5. The manifest is output as JSON (or published via Hub API)

## 3. Recipe manifest format

```json
{
  "id": "recipe-abc123",
  "name": "triage-verify-pipeline",
  "version": "1.0.0",
  "pipeline": [
    {
      "step": 1,
      "gene_id": "gene-triage-1",
      "condition": "signals.contains('error')",
      "optional": false
    },
    {
      "step": 2,
      "gene_id": "gene-verify-1",
      "condition": "outcome.status == 'success'",
      "optional": true
    }
  ],
  "metadata": {
    "source": "skill2recipe",
    "skills": ["triage", "verify"],
    "created": "2025-07-19T12:00:00Z"
  }
}
```

Reference manifest: `examples/recipe.manifest.json`

## 4. List available recipes

```bash
# List recipes from Hub cache
uv run evolver recipe list

# Show specific recipe details
uv run evolver recipe show recipe-abc123

# Clear recipe cache
uv run evolver recipe cache-clear
```

## 5. Apply a recipe

```bash
# Apply recipe (executes all genes in pipeline order)
uv run evolver recipe apply recipe-abc123

# Dry-run to preview without executing
uv run evolver recipe apply recipe-abc123 --dry-run
```

## 6. Cache management

```bash
# List cached recipes (local copies from Hub)
uv run evolver recipe cache-list

# Clear cache
uv run evolver recipe cache-clear
```

## 7. End-to-end workflow

```bash
# 1. Write your Agent Skills as SKILL.md files
mkdir -p skills/triage
cat > skills/triage/SKILL.md << 'EOF'
# Triage Skill

## Description
Analyzes error patterns and categorizes by severity.

## Usage
Applied when `log_error` or `test_failure` signals are detected.
EOF

# 2. Compose them into a recipe
uv run evolver skill2recipe skills/triage skills/verify

# 3. Inspect the generated recipe
cat recipe-output.json

# 4. Publish to Hub (if connected)
uv run evolver publish recipe-abc123

# 5. Apply the recipe to your project
uv run evolver recipe apply recipe-abc123
```

## 8. Troubleshooting

| Symptom | Solution |
|---------|----------|
| "no skills found" | Verify skill directories exist and contain SKILL.md files |
| Recipe validation fails | Check that generated genes pass GEP schema validation |
| Composition produces no genes | SKILL.md may be too short; add more content (min 50 chars) |
| `recipe apply` fails | Ensure the recipe is cached (`recipe cache-list`) or fetch from Hub |
| "missing condition field" | Add `condition` to your manifest pipeline steps |
