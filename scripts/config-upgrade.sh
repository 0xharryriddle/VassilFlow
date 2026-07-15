#!/usr/bin/env bash
#
# config-upgrade.sh - Upgrade config.yaml to match config.example.yaml
#
# 1. Runs version-specific migrations (value replacements, renames, etc.)
# 2. Merges missing fields from the example into the user config
# 3. Backs up config.yaml to config.yaml.bak before modifying.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXAMPLE="$REPO_ROOT/config.example.yaml"

# Resolve config.yaml location: env var > backend/ > repo root
if [ -n "${VASSILFLOW_CONFIG_PATH:-}" ] && [ -f "$VASSILFLOW_CONFIG_PATH" ]; then
    CONFIG="$VASSILFLOW_CONFIG_PATH"
elif [ -f "$REPO_ROOT/backend/config.yaml" ]; then
    CONFIG="$REPO_ROOT/backend/config.yaml"
elif [ -f "$REPO_ROOT/config.yaml" ]; then
    CONFIG="$REPO_ROOT/config.yaml"
else
    CONFIG=""
fi

if [ ! -f "$EXAMPLE" ]; then
    echo "✗ config.example.yaml not found at $EXAMPLE"
    exit 1
fi

if [ -z "$CONFIG" ]; then
    echo "No config.yaml found — creating from example..."
    cp "$EXAMPLE" "$REPO_ROOT/config.yaml"
    echo "OK config.yaml created. Please review and set your API keys."
    exit 0
fi

# Use inline Python to do migrations + recursive merge with PyYAML
if command -v cygpath >/dev/null 2>&1; then
    CONFIG_WIN="$(cygpath -w "$CONFIG")"
    EXAMPLE_WIN="$(cygpath -w "$EXAMPLE")"
else
    CONFIG_WIN="$CONFIG"
    EXAMPLE_WIN="$EXAMPLE"
fi

cd "$REPO_ROOT/backend" && CONFIG_WIN_PATH="$CONFIG_WIN" EXAMPLE_WIN_PATH="$EXAMPLE_WIN" uv run python -c "
import os
import sys, shutil, copy, re
from pathlib import Path

import yaml

config_path = Path(os.environ['CONFIG_WIN_PATH'])
example_path = Path(os.environ['EXAMPLE_WIN_PATH'])

with open(config_path, encoding='utf-8') as f:
    raw_text = f.read()
    user = yaml.safe_load(raw_text) or {}

with open(example_path, encoding='utf-8') as f:
    example = yaml.safe_load(f) or {}

def parse_config_version(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


user_version = parse_config_version(user.get('config_version', 0))
example_version = parse_config_version(example.get('config_version', 0))

if user_version >= example_version:
    print(f'OK config.yaml is already up to date (version {user_version}).')
    sys.exit(0)

print(f'Upgrading config.yaml: version {user_version} -> {example_version}')
print()

# ── Migrations ───────────────────────────────────────────────────────────
# Each migration targets a specific version upgrade.
# 'replacements': list of (old_string, new_string) applied to the raw YAML text.
#   This handles value changes that a dict merge cannot catch.
# 'value_replacements': list of exact YAML string values to rewrite after parsing.

MIGRATIONS = {
    1: {
        'description': 'Rename src.* module paths to vassilflow.*',
        'replacements': [
            ('src.community.', 'vassilflow.community.'),
            ('src.sandbox.', 'vassilflow.sandbox.'),
            ('src.models.', 'vassilflow.models.'),
            ('src.tools.', 'vassilflow.tools.'),
        ],
    },
    19: {
        'description': 'Add structured VassilFlow Office tools alongside existing file capabilities',
        'list_additions': [
            (
                'tools',
                'name',
                {
                    'name': 'office_inspect',
                    'group': 'file:read',
                    'use': 'vassilflow.community.office.tools:office_inspect_tool',
                },
                {'read_file'},
            ),
            (
                'tools',
                'name',
                {
                    'name': 'office_edit',
                    'group': 'file:write',
                    'use': 'vassilflow.community.office.tools:office_edit_tool',
                },
                {'write_file', 'str_replace'},
            ),
            (
                'tools',
                'name',
                {
                    'name': 'office_render',
                    'group': 'file:write',
                    'use': 'vassilflow.community.office.tools:office_render_tool',
                },
                {'write_file', 'str_replace'},
            ),
        ],
    },
    # Future migrations go here:
    # 2: {
    #     'description': '...',
    #     'replacements': [('old', 'new')],
    # },
}

# Apply migrations in order for versions (user_version, example_version]
migrated = []
value_replacements = []
list_additions = []
for version in range(user_version + 1, example_version + 1):
    migration = MIGRATIONS.get(version)
    if not migration:
        continue
    desc = migration.get('description', f'Migration to v{version}')
    for old, new in migration.get('replacements', []):
        if old in raw_text:
            raw_text = raw_text.replace(old, new)
            migrated.append(f'{old} -> {new}')
    value_replacements.extend(migration.get('value_replacements', []))
    list_additions.extend(migration.get('list_additions', []))

# Re-parse after text migrations
user = yaml.safe_load(raw_text) or {}

for list_key, identity_key, item, required_names in list_additions:
    values = user.get(list_key)
    if not isinstance(values, list):
        # Let the recursive merge add the complete example list when the key is absent.
        continue
    existing_names = {
        value.get(identity_key)
        for value in values
        if isinstance(value, dict) and isinstance(value.get(identity_key), str)
    }
    identity = item.get(identity_key)
    if identity in existing_names or not existing_names.intersection(required_names):
        continue
    values.append(copy.deepcopy(item))
    migrated.append(f'{list_key}: added {identity}')

if value_replacements:
    def replace_values(node, path=''):
        if isinstance(node, dict):
            for key, value in list(node.items()):
                key_path = f'{path}.{key}' if path else str(key)
                node[key] = replace_values(value, key_path)
        elif isinstance(node, list):
            for index, value in enumerate(list(node)):
                node[index] = replace_values(value, f'{path}[{index}]')
        elif isinstance(node, str):
            for old, new in value_replacements:
                if node == old:
                    migrated.append(f'{path}: {old} -> {new}')
                    return new
        return node

    user = replace_values(user)

if migrated:
    print(f'Applied {len(migrated)} migration(s):')
    for m in migrated:
        print(f'  ~ {m}')
    print()

# ── Merge missing fields ─────────────────────────────────────────────────

added = []

def merge(target, source, path=''):
    \"\"\"Recursively merge source into target, adding missing keys only.\"\"\"
    for key, value in source.items():
        key_path = f'{path}.{key}' if path else key
        if key not in target:
            target[key] = copy.deepcopy(value)
            added.append(key_path)
        elif isinstance(value, dict) and isinstance(target[key], dict):
            merge(target[key], value, key_path)

merge(user, example)

# Always update config_version
user['config_version'] = example_version

# ── Write ─────────────────────────────────────────────────────────────────

backup = config_path.with_suffix('.yaml.bak')
shutil.copy2(config_path, backup)
print(f'Backed up to {backup.name}')

with open(config_path, 'w', encoding='utf-8') as f:
    yaml.dump(user, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

if added:
    print(f'Added {len(added)} new field(s):')
    for a in added:
        print(f'  + {a}')

if not migrated and not added:
    print('No changes needed (version bumped only).')

print()
print(f'OK config.yaml upgraded to version {example_version}.')
print('  Please review the changes and set any new required values.')
"
