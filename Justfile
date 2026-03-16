set dotenv-load

# First-time setup: PIN flow + thermostat discovery
climate-auth:
    uv run python -m climate.sync auth

# List thermostats and climate refs on this account
climate-list:
    uv run python -m climate.sync list

# Show current thermostat state
climate-status *ARGS:
    uv run python -m climate.sync status {{ARGS}}

# Push schedule.yaml to Ecobee
climate-sync *ARGS:
    uv run python -m climate.sync sync {{ARGS}}

# Preview expanded schedule without pushing
climate-sync-dry *ARGS:
    uv run python -m climate.sync sync --dry-run {{ARGS}}

# Validate schedule.yaml matches the live schedule on Ecobee
climate-validate *ARGS:
    uv run python -m climate.sync validate {{ARGS}}

# Snapshot current comfort mode temps from Ecobee into comforts.yaml
climate-comforts-capture *ARGS:
    uv run python -m climate.sync capture-comforts {{ARGS}}

# Push comforts.yaml setpoints to Ecobee
climate-comforts-sync *ARGS:
    uv run python -m climate.sync sync-comforts {{ARGS}}

# Preview comfort changes without pushing
climate-comforts-sync-dry *ARGS:
    uv run python -m climate.sync sync-comforts --dry-run {{ARGS}}

# Install dependencies (run once after clone)
install:
    uv sync

# Generate .env from 1Password (run after clone or when secrets change)
# Verifies the new .env has at least every key the old .env had (guards against accidental omissions).
dotenv:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -f .env ]; then
        old_keys=$(grep -v '^#' .env | grep -v '^[[:space:]]*$' | cut -d= -f1 | sort)
    fi
    op inject -f -i .env.template -o .env
    if [ -n "${old_keys:-}" ]; then
        new_keys=$(grep -v '^#' .env | grep -v '^[[:space:]]*$' | cut -d= -f1 | sort)
        missing=$(comm -23 <(echo "$old_keys") <(echo "$new_keys"))
        if [ -n "$missing" ]; then
            echo "ERROR: these keys were in .env but are missing from the new .env:"
            echo "$missing"
            echo "Add them to .env.template if they should be kept, then re-run just dotenv."
            exit 1
        fi
    fi
