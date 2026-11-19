# How picklelab should get its application images (options)

Status: **options sketch, no decision yet.** Nothing here changes a service.

Background: on 2026-11-14 three images built on picklelab lost layers on disk
(`obsidian-sync:latest`, `brineworks-server:local`, `openclaw-goplaces-node:latest`)
and Brent was down until a rebuild. All 25 registry-pulled images were intact, and so
was the rootless `ci` store. Five other host-built images were also intact. The cause
is **not settled**: the weekly `docker builder prune` is the leading suspect, but a
clean repro did not break anything. Evidence and hypotheses:
[`docs/research/picklelab-image-store-damage-2026-11/`](../research/picklelab-image-store-damage-2026-11/README.md)
(PR #226, branch `docker-prune-detector`; the link resolves once it merges).

## What we're deciding

Where application images get built, and where picklelab gets them from, so that
damage like this is caught quickly and recovery is cheap. Because the cause is
unknown, an option counts for more if it helps **whatever** the cause turns out to be.

## The measured fact we can lean on

The only clean split in the data is **pulled vs built here**: every damaged image was
built on the host, and every pulled image survived. That does not prove local builds
are the cause (five local builds survived too). But "the host only holds images it can
re-pull" has two benefits that hold under any cause:

1. Recovery becomes `docker pull <digest>`. No source checkout, build cache or build
   time on the Celeron.
2. A rollback is a pull of an older digest, not a rebuild of an older commit.

## Today, for reference

`just deploy-<service>` pushes, then over ssh runs `git pull` and `deploy.sh`, which
builds the image on the host from source:

| Image | Built by |
|---|---|
| `brineworks-server:local` | unit `ExecStart` runs `docker compose up -d --build`, so **every start rebuilds**, not only deploys |
| `openclaw-goplaces-node`, `openclaw-gog-mcp` | `openclaw/deploy.sh` (`$COMPOSE build ...`), gog-mcp from the private pickleclaw repo |
| `obsidian-sync`, `open-webui:local`, `open-terminal:local` | the service's `deploy.sh` from a Dockerfile in this repo |
| `nikke:local` | `nikke/deploy.sh`, from the nikke-roster-scanner repo |
| `openclaw` itself, Woodpecker, the rest | pulled from a registry already |

Rollback today is reverting the commit and redeploying, which rebuilds. Base images
and package installs aren't pinned, so a rebuild of an old commit isn't the old image.

Brent rule ([ADR 0003](../adr/0003-refuse-deploys-while-brent-is-active.md)): the
quiet check runs first in `deploy.sh`, then clones and builds, then restarts. The
build time sits between the check and the restart, so a turn can start in that gap.

## Options

### A. Keep building on the host, check after every deploy, rebuild on failure

- **Deploy:** as today, plus `ctr -n moby images check` on the service's image after
  the build and a daily (not weekly) check from a timer. On failure, delete and
  rebuild the image.
- **Rollback:** unchanged (rebuild an older commit).
- **Protects against:** finding damage within a day instead of at the next restart.
  Does nothing to make damage less likely, under any hypothesis.
- **Effort:** small. The check script exists in PR #226.
- **New failure modes:** auto-rebuild on a store we don't understand can hide the
  signal we need to find the cause, and a rebuild of brineworks-server or the openclaw
  images restarts Brent. Rebuilds still need GitHub, the private repos and minutes of
  CPU.
- **Secrets:** none new.
- **Brent rule:** unchanged. An automatic rebuild would have to run the quiet check
  too, or it's a back door around ADR 0003.

The **detection half is worth doing under every option**. The automatic rebuild is
the part to skip: alert (Telegram via `notify`) and let a person decide.

### B. Build in CI, push to a registry, host only pulls

- **Deploy:** a push to main builds the image in CI and pushes it tagged with the
  commit SHA. `just deploy-<service>` (or `deploy.sh`) waits for that tag to exist,
  pulls it by digest, and restarts. compose files use `image: <registry>/<name>@<digest>`
  (or `:<sha>`) instead of `build:`. brineworks-server's unit drops `--build`.
- **Rollback:** deploy an older SHA tag. The image is already in the registry and
  often still on the host. No build.
- **Protects against:** under H1 (prune hits local-build content), the main store
  has no local builds left for it to hit. Under H3 (stale metadata on restart) or an
  unknown cause, it doesn't prevent damage but turns recovery into a pull. It removes
  the cross-talk between build cache and image content on the main store entirely.
- **Effort:** medium, per service. A pipeline per image-producing repo (brineworks,
  pickleclaw for gog-mcp, nikke-roster-scanner, picklehome for obsidian-sync,
  goplaces-node, open-webui), deploy scripts switched from `build` to `pull`. Can be
  done one service at a time.
- **Builder choice:**
  - *Woodpecker on picklelab.* Fits the "CI is Woodpecker" consolidation. But the agent
    runs steps on the rootless `ci` daemon, and the usual buildx plugin wants a
    privileged container plus a trusted repo. Needs a spike (buildx in rootless, or
    kaniko/buildah unprivileged). Builds still eat the Celeron, now competing with the
    16-minute brineworks test suite under `WOODPECKER_MAX_WORKFLOWS=2`.
  - *GitHub-hosted Actions.* Pushes to ghcr with the built-in `GITHUB_TOKEN`
    (`packages: write`), so no push PAT. Takes build load off picklelab. Costs Actions
    minutes on private repos and reintroduces a second CI system.
- **New failure modes:** registry or GitHub outage blocks deploys (running services
  keep running, the image is local). Pull token expires or gets revoked. Deploy is no
  longer one synchronous step: "pushed but image not built yet" needs a clear wait and
  error. If damage ever shows up in a pulled image, this option loses its main argument.
- **Secrets/auth:** a push credential in CI (none with Actions + `GITHUB_TOKEN`; a
  `write:packages` PAT as a Woodpecker secret otherwise). A `read:packages` token on
  the host for private packages, in 1Password, used via `docker login` from `op run`
  or a credential helper so it isn't left in root's `~/.docker/config.json` as
  plaintext. Images from private repos must stay private packages.
- **Brent rule:** gets better. The build happens off the deploy path, so the gap between
  the quiet check and the restart shrinks to a pull. Deploys that only build (CI) never
  need the check.

### C. Same as B, but a registry on picklelab or the tailnet

- **Deploy/rollback:** as B, pointing at `registry.<tailnet>` (`registry:2` or zot)
  behind Tailscale Services, storage on its own path (not the containerd store).
- **Protects against:** same as B. Also removes the ghcr dependency and any GitHub
  Packages storage limit for private images (check the current limits before choosing B).
- **Effort:** B plus running and backing up (or deliberately not backing up) one more
  service.
- **New failure modes:** the registry lives on the box it serves. If the disk or the
  registry container is down, nothing can re-pull, which is exactly when you need it.
  Bootstrap order matters after a rebuild of the host. No other always-on tailnet host
  exists yet (seapickle is a Pi 3B+; the NAS is "future").
- **Secrets/auth:** tailnet ACL instead of tokens, or htpasswd for push.
- **Brent rule:** as B.

### D. Change the main daemon's storage (classic overlay2 graph driver)

- **Deploy/rollback:** unchanged from today.
- **Protects against:** H1 only if the bug lives in the containerd image store's GC
  or leases. Says nothing about H3 or an unknown cause.
- **Effort:** one risky migration: switching drivers hides every existing image, so
  everything is re-pulled or rebuilt, with downtime for every service.
- **New failure modes:** moves off Docker's default store onto the path Docker is
  phasing out. The rootless `ci` store runs the containerd store and was fine, which is
  weak evidence the store itself isn't the problem.
- **Brent rule:** unchanged.

Not recommended without evidence pointing at the containerd store.

### E. Nothing beyond PR #226 (and the needrestart change)

- **What it is:** no `docker builder prune`, `ctr images check` before and after the
  weekly prune, failing the unit on damage. needrestart no longer restarts containerd.
- **Protects against:** H1 if the prune is the cause. Damage from anything else is found
  within a week, or at the next restart.
- **Effort:** done. **Cost:** build cache now grows unbounded on `/srv/containerd`
  (123G free today), which needs some other cap eventually.
- **Brent rule:** unchanged.

## Recommendation

**B, one service at a time, starting with brineworks-server,** plus the detection half
of A (image check after each deploy and daily, alert on failure, no automatic rebuild).

Why B: it's the only option that improves recovery and rollback under every hypothesis,
and it lines the host up with the one pattern that held (pulled images survived). It
also tightens the ADR 0003 window. brineworks-server goes first because it's
Brent-critical, it was damaged, and its unit rebuilds on every start.

Registry: ghcr, with the builder decided by a short spike. If buildx works on the
rootless Woodpecker daemon without `privileged`, use Woodpecker; if not, use
GitHub-hosted Actions for image builds only and keep tests on Woodpecker.

## What would change this

- **H1 confirmed and fully explained by `docker builder prune`** (for example a repro
  that breaks a store): E is enough; B drops to a rollback nicety.
- **Damage in a registry-pulled image, or in the `ci` store:** B's main argument is gone.
  Look at containerd itself (H3, metadata rollback) and reconsider D.
- **GitHub Packages limits or cost make private images impractical:** C instead of ghcr.
- **No unprivileged way to build images in Woodpecker and no appetite for Actions:**
  stay on A's detection plus E until one exists.

## Noticed while writing this

On 2026-11-15, `docker image ls` on picklelab fails with
`blob sha256:438abc8a... not found`, so the main store is still damaged and the image
listing itself is broken until the rebuild (task `9bc7abb8`) is done. Not touched.
