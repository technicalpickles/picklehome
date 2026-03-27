# Climate Auto-Switch Docker Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Containerize the climate comfort-switch timer so it runs as a Docker image on picklelab, with deps baked in and local macOS testing support.

**Architecture:** Slim Python Docker image built from `homelab/services/climate-auto-switch/`, with repo root as build context. `uv sync` at build time bakes in deps. Compose files handle env differences between local (Mac) and picklelab. Systemd timer triggers `docker compose run --rm`. Ecobee token file persisted via bind mount.

**Tech Stack:** Docker, Docker Compose, uv, systemd, Python 3.12+

**Design doc:** `docs/plans/2026-03-26-climate-auto-switch-docker.md`

---

### Task 1: Add ECOBEE_TOKEN_PATH env var support

**Files:**
- Modify: `climate/ecobee/auth.py:9` (DEFAULT_TOKEN_PATH)
- Test: `tests/climate/ecobee/test_auth.py`

**Step 1: Write the failing test**

Add to `tests/climate/ecobee/test_auth.py`:

```python
def test_default_token_path_from_env(monkeypatch, tmp_path):
    """ECOBEE_TOKEN_PATH env var overrides the default."""
    custom_path = tmp_path / "custom-tokens.json"
    monkeypatch.setenv("ECOBEE_TOKEN_PATH", str(custom_path))

    # Re-import to pick up the env var
    from importlib import reload
    import climate.ecobee.auth as auth_mod
    reload(auth_mod)

    assert auth_mod.DEFAULT_TOKEN_PATH == custom_path
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/climate/ecobee/test_auth.py::test_default_token_path_from_env -v`
Expected: FAIL (DEFAULT_TOKEN_PATH ignores env var)

**Step 3: Write minimal implementation**

In `climate/ecobee/auth.py`, replace line 9:

```python
DEFAULT_TOKEN_PATH = Path.home() / ".local" / "state" / "picklehome" / "ecobee-tokens.json"
```

with:

```python
def _default_token_path() -> Path:
    env_path = os.environ.get("ECOBEE_TOKEN_PATH")
    if env_path:
        return Path(env_path)
    return Path.home() / ".local" / "state" / "picklehome" / "ecobee-tokens.json"

DEFAULT_TOKEN_PATH = _default_token_path()
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/climate/ecobee/test_auth.py -v`
Expected: ALL PASS (including existing tests)

**Step 5: Commit**

```
feat(climate/ecobee): support ECOBEE_TOKEN_PATH env var override
```

---

### Task 2: Create the Dockerfile

**Files:**
- Create: `homelab/services/climate-auto-switch/Dockerfile`

**Step 1: Write the Dockerfile**

```dockerfile
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install deps first (layer caching: deps change less often than code)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# Copy the climate package
COPY climate/ climate/

# Install the project itself (uses cached deps layer)
RUN uv sync --frozen

ENTRYPOINT ["uv", "run", "python", "-m", "climate.sync", "comfort-switch", "auto", "--clear-holds"]
```

**Step 2: Verify the image builds locally**

Run from repo root:
```bash
docker build -f homelab/services/climate-auto-switch/Dockerfile -t climate-auto-switch .
```
Expected: Successful build, no errors.

**Step 3: Commit**

```
feat(homelab): add Dockerfile for climate-auto-switch
```

---

### Task 3: Create compose files

**Files:**
- Create: `homelab/services/climate-auto-switch/compose.yaml`
- Create: `homelab/services/climate-auto-switch/compose.picklelab.yaml`

**Step 1: Write the base compose file (local/Mac defaults)**

`homelab/services/climate-auto-switch/compose.yaml`:

```yaml
services:
  climate-auto-switch:
    build:
      context: ../../..
      dockerfile: homelab/services/climate-auto-switch/Dockerfile
    env_file:
      - ../../../.env
    volumes:
      - ${ECOBEE_TOKEN_DIR:-~/.local/state/picklehome}:/data/tokens
    environment:
      - ECOBEE_TOKEN_PATH=/data/tokens/ecobee-tokens.json
```

**Step 2: Write the picklelab override**

`homelab/services/climate-auto-switch/compose.picklelab.yaml`:

```yaml
services:
  climate-auto-switch:
    env_file:
      - /opt/homelab/.env
    volumes:
      - /srv/data/climate-auto-switch:/data/tokens
```

**Step 3: Test locally with compose**

Run from `homelab/services/climate-auto-switch/`:
```bash
docker compose run --rm climate-auto-switch
```
Expected: The comfort-switch command runs, reads `.env`, reads tokens from the bind mount, and exits. Output shows thermostat status and any mode switch.

**Step 4: Verify token file is writable through the mount**

After the run, check that the token file was updated (modified timestamp should be recent if a token refresh happened). If no refresh needed, verify the file is still readable:
```bash
cat ~/.local/state/picklehome/ecobee-tokens.json
```

**Step 5: Commit**

```
feat(homelab): add compose files for climate-auto-switch
```

---

### Task 4: Update systemd service unit

**Files:**
- Modify: `homelab/services/climate-auto-switch/climate-auto-switch.service`

**Step 1: Update the service unit**

Replace the contents of `climate-auto-switch.service` with:

```ini
[Unit]
Description=Climate comfort-switch auto (outdoor temp check)
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=oneshot
TimeoutStartSec=300
WorkingDirectory=/opt/homelab/homelab/services/climate-auto-switch
ExecStart=/usr/bin/docker compose -f compose.yaml -f compose.picklelab.yaml run --rm climate-auto-switch
```

**Step 2: Commit**

```
feat(homelab): update climate-auto-switch service to use docker compose
```

---

### Task 5: Remove run.sh

**Files:**
- Delete: `homelab/services/climate-auto-switch/run.sh`

**Step 1: Remove the file**

```bash
git rm homelab/services/climate-auto-switch/run.sh
```

**Step 2: Commit**

```
refactor(homelab): remove run.sh, replaced by docker compose
```

---

### Task 6: Add deploy-climate task to Justfile

**Files:**
- Modify: `Justfile`

**Step 1: Add the deploy task**

Append to `Justfile`:

```just
# Deploy climate-auto-switch to picklelab: pull latest code and rebuild image
deploy-climate host="picklelab":
    ssh {{host}} "cd /opt/homelab && git pull && cd homelab/services/climate-auto-switch && docker compose -f compose.yaml -f compose.picklelab.yaml build"
```

**Step 2: Verify it appears in task list**

Run: `just --list`
Expected: `deploy-climate` appears with its description.

**Step 3: Commit**

```
feat: add deploy-climate just task for picklelab deploys
```

---

### Task 7: Update homelab README

**Files:**
- Modify: `homelab/README.md`

**Step 1: Update the setup instructions**

Replace the climate-auto-switch section in `homelab/README.md` to reflect the Docker-based approach:

- Remove references to `uv`, `scripts/dotenv` on the host, and the `picklehome` user
- Setup is now: clone repo, generate `.env`, create `/srv/data/climate-auto-switch/`, seed the token file, build the image, symlink and enable systemd units
- Manual trigger uses `docker compose run --rm`
- Deploys use `just deploy-climate` from Mac

**Step 2: Commit**

```
docs(homelab): update climate-auto-switch setup for Docker deployment
```

---

### Task 8: End-to-end local test

**No files changed. Verification only.**

**Step 1: Clean build**

From `homelab/services/climate-auto-switch/`:
```bash
docker compose build --no-cache
```

**Step 2: Run the container**

```bash
docker compose run --rm climate-auto-switch
```
Expected: Command runs successfully, outputs thermostat status and comfort mode decision.

**Step 3: Verify token persistence**

Check the token file on the host was readable/writable through the mount:
```bash
ls -la ~/.local/state/picklehome/ecobee-tokens.json
```

**Step 4: Verify no leftover containers**

```bash
docker ps -a --filter name=climate-auto-switch
```
Expected: No containers listed (`--rm` cleaned up).
