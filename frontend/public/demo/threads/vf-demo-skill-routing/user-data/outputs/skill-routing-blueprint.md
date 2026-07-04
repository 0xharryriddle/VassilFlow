# Skill Routing Blueprint

## Stable Identity

VassilFlow executes skills through category-qualified IDs:

- `public:research-brief`
- `custom:legal-review`
- `workspace:artifact-builder`

Display labels can change without changing execution identity.

## Routing Flow

1. Parse the user intent.
2. Select candidate skills by category and capability metadata.
3. Resolve conflicts by exact ID first, then by category preference.
4. Record selected IDs in run metadata.
5. Load only the selected skill instructions.

## Observability

Every skill activation should include:

- requested capability
- selected skill ID
- category
- version or content hash when available
- reason for selecting the skill
