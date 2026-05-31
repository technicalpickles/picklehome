# github-actions-runner

Self-hosted GitHub Actions runner for [pirpg](https://github.com/technicalpickles/pirpg).

GitHub-hosted runners are blocked on that private repo (account billing failed / spending limit), so CI couldn't run. This runs a runner on picklelab instead. It's a [`myoung34/github-runner`](https://github.com/myoung34/docker-github-actions-runner) container that polls GitHub over outbound HTTPS, so there's no inbound port and nothing to expose.

The pirpg workflow targets it with `runs-on: [self-hosted, picklelab]`.

## Auth model: register once, reuse credentials

This is the important part. GitHub's own runner-as-a-service model registers a runner **once** and then reuses stored credentials forever; it does not re-register on restart. The registration token is a one-time, ~1-hour setup credential, not ongoing auth.

In a container, the runner's credentials normally live inside the container filesystem and would be lost when `docker compose down` destroys the container (e.g. on reboot), forcing a re-register with a token that has since expired. Two settings make the container behave like GitHub's persistent model:

- **`CONFIGURED_ACTIONS_RUNNER_FILES_DIR=/runner-config`** plus a named volume mounted there. The entrypoint copies the runner config files (`.runner`, `.credentials`, `.credentials_rsaparams`, `_diag`) to/from this dir and skips `config.sh` whenever `/actions-runner/.runner` already exists.
- **`DISABLE_AUTOMATIC_DEREGISTRATION=true`**. Without it, the container deregisters the runner on stop, which would wipe the persisted credentials and defeat the whole thing.

Net result: the runner survives reboots without a fresh token. The `GITHUB_RUNNER_TOKEN` in `.env` only matters at first bootstrap (or a re-bootstrap after the volume is wiped); in steady state it can be expired and nothing breaks.

## Files

| File | Purpose |
|------|---------|
| `compose.yaml` | The whole service. Image, env, the persistence volume. |
| `deploy.sh` | Pulls the image, links the systemd unit, enables + restarts it. |
| `github-actions-runner.service` | systemd unit (oneshot + RemainAfterExit, `compose up -d` / `down`). |
| `.env.vars` | The two env vars this service needs, filtered from the master `.env`. |

**No `compose.picklelab.yaml`.** Other services split base/prod, but this one only ever runs on picklelab and has no prod-vs-local difference. An earlier draft mirrored vikunja's `env_file: [/opt/homelab/.env]` override, which would have injected the *entire* homelab secret set (UniFi, Hue, Ecobee, ...) into a container that runs arbitrary CI jobs. The runner gets its two vars via `${...}` interpolation from the auto-loaded project `.env`, so the override was both dead weight and a secret leak. Dropped it.

## First-time setup (from Mac)

```bash
# 1. Mint a registration token (valid ~1h) and store it in the 1Password item
#    "GitHub Actions Runner pirpg" (picklehome vault), field `token`:
gh api -X POST repos/technicalpickles/pirpg/actions/runners/registration-token --jq .token
#    The repo URL lives in the same item's `repro_url` field (sic).

just dotenv                  # generate .env from 1Password
just deploy-github-runner    # scp .env, pull image, install + start the systemd unit
```

Confirm it registered:

```bash
gh api repos/technicalpickles/pirpg/actions/runners --jq '.runners[] | "\(.name) \(.status) [\([.labels[].name]|join(","))]"'
# picklelab online [self-hosted,Linux,X64,picklelab]
```

## Deploy updates

```bash
just deploy-github-runner
```

Once registered, redeploys reuse the persisted credentials. The `.env` token does not need to be current.

## Logs / status

```bash
just github-runner-logs      # tail -f container logs
just github-runner-status    # systemd + docker ps
```

## Re-bootstrap (credentials lost)

Only needed if the `runner-config` volume is deleted, or GitHub deregistered the runner (e.g. 30+ days offline). Registration tokens are single-use and expire in ~1h, so mint a fresh one:

```bash
gh api -X POST repos/technicalpickles/pirpg/actions/runners/registration-token --jq .token
# put it in the 1Password item's `token` field, then:
just dotenv
# remove any stale "picklelab" runner so the name is free:
gh api -X DELETE repos/technicalpickles/pirpg/actions/runners/$(gh api repos/technicalpickles/pirpg/actions/runners --jq '.runners[] | select(.name=="picklelab") | .id')
just deploy-github-runner
```

## Troubleshooting

- **`Http response code: NotFound from POST .../runner-registration` (404) at bootstrap**: the registration token is expired or already used. Mint a fresh one and re-bootstrap (above). This only happens during initial registration; a configured runner reuses credentials and never hits this.
- **`A session for this runner already exists. Retrying until reconnected.`**: transient, happens if the container is recreated faster than GitHub expires the previous session. It self-heals in ~30s. Just wait.
- **Runner shows `offline` right after a deploy**: give it ~30s to reconnect before worrying.

## Adding a runner for another repo

GitHub registers self-hosted runners at the **repo, org, or enterprise** level, never at the user-account level. `technicalpickles` is a user account, so each personal repo needs its own repo-scoped runner (a separate container). There is no "one runner for all my repos" unless you move repos into a GitHub org and use an org-level runner.

### Option A: GitHub org (one runner, many repos)

If you create a GitHub org and move repos into it, register one runner with `RUNNER_SCOPE=org` + `ORG_NAME=<org>`. Every repo in the org can then use it via `runs-on: [self-hosted, picklelab]`. Cleanest if you expect several repos; the cost is a one-time org migration.

### Option B: one runner per repo on this host (no org)

This service is currently hardcoded to pirpg. To add a second repo by copying:

1. Duplicate `homelab/services/github-actions-runner/` to `.../github-actions-runner-<repo>/`.
2. Retarget the copy:
   - `compose.yaml`: unique `RUNNER_NAME`, repo-specific `LABELS` if you want per-repo routing, and a **distinct `runner-config` volume name** (else it collides with pirpg's). The Compose project name (dir name, or `COMPOSE_PROJECT_NAME`) namespaces the container + volumes.
   - `.env.vars` + `.env.template`: repo-specific var names (e.g. `GITHUB_RUNNER_TOKEN_<REPO>`) so they don't clash with pirpg's global pair.
   - `<service>.service`: new unit name, `Description`, and `WorkingDirectory`.
   - `deploy.sh`: new `SERVICE_DIR`.
   - `Justfile`: new `deploy-github-runner-<repo>` / `-logs` / `-status` recipes.
3. New 1Password item (or new fields) for that repo's registration token + repo URL.
4. Bootstrap exactly like pirpg (mint token -> 1Password -> `just dotenv` -> deploy).

That's ~10-15 edits and easy to get subtly wrong (volume/env-var collisions, two units fighting).

### Making Option B push-button (the refactor, when it's worth it)

Convert this single service into a **systemd template unit** so each repo is one command:

- `github-runner@.service` using `%i` for the instance (repo) name, with per-instance `WorkingDirectory`.
- `compose.yaml` parameterized by env: `COMPOSE_PROJECT_NAME=github-runner-%i`, `RUNNER_NAME`, `REPO_URL`, per-instance volume.
- Per-repo `.env` (one 1Password item per repo, or one item with per-repo fields).
- `just deploy-github-runner repo=<name>` -> scp `.env` -> `systemctl enable --now github-runner@<name>`.

Then repo #3, #4 are a single recipe call plus a fresh registration token. Roughly an hour to build the template. Not worth it for just one more repo; clearly worth it past two or three.

### Resource ceiling

Each runner is an always-on container, but idle runners just poll and cost almost nothing. The J3455 + 16 GB handles a handful. The real limit is **disk** (root has run around 9-10 GB free): each running job checks out the repo + dependencies into `_work`, so the failure mode is many runners building *simultaneously*, not many runners sitting idle. Watch `df -h /` if you add several.

## Security notes

- **No `/var/run/docker.sock` mount.** The runner does not give CI jobs access to the host Docker daemon. pirpg's CI is Node/npm and doesn't need it. Mounting the socket would grant any job root-equivalent control of picklelab, so it's left off by default.

  Add it back (a `- /var/run/docker.sock:/var/run/docker.sock` line under `volumes:` in `compose.yaml`) only if a workflow genuinely needs Docker *on the runner*:
  - building or pushing Docker images (`docker build` / `docker/build-push-action`)
  - docker-in-docker workflows
  - container-based actions (a step whose `uses:` action declares `runs.using: docker`)
  - job-level `services:` containers (GitHub spins these up via the host Docker daemon)

  If you do, treat it as a deliberate trust decision: it's only safe because this is a solo private repo with no fork PRs running untrusted code.
- The runner only carries its own two env vars, not the master `.env` (see the no-`compose.picklelab.yaml` note above).
