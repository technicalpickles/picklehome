# Publishing picklelab's built images to GHCR (design)

Status: **design, not implemented.** A snapshot from 2026-11-15. Check the code and
`git log` before treating anything here as current. Nothing in this document has been
run against picklelab except the read-only checks listed under "Measured".

Follows [the options sketch](2026-11-15-picklelab-built-images-options.md) (branch
`picklelab-built-images-options`; the link resolves once it merges) and picks its
**option B**: build in CI, push to a registry, and have the host only pull. This
document fills in the registry choice, the build mechanics on the rootless Woodpecker
daemon, the auth, and a pilot. The tools and techniques compared along the way are in
[`docs/research/container-registries/findings.md`](../research/container-registries/findings.md).

## Goal

Make picklelab hold only images it can re-pull, so that recovery from a damaged image
store is `docker pull <digest>` and a rollback is a pull of an older digest, not a
rebuild of an older commit.

Why now: on 2026-11-14 three host-built images lost layers and Brent was down until a
rebuild. Every registry-pulled image survived (details and hypotheses in the options
sketch). Disk space is no longer the pressure it was when taskwarrior `6885ef30`
("build off-box and push to a registry") was filed, so this is about resilience,
rollback and shipping what CI tested, not about disk.

Non-goals:

- A registry running on picklelab or the tailnet (option C in the sketch).
- A pull-through cache or mirror for upstream images.
- Changing the main daemon's storage driver.

## Measured

Read-only, over ssh to picklelab on 2026-11-15:

- `/srv` is 99G with 84G free. `/` is 50G with 39G free. The sketch cites 123G free on
  the containerd path, which is its own mount.
- 4 cores (`nproc`) and 15GiB RAM. The CPU is a Celeron J3455 (`homelab/README.md`),
  so "4 cores" overstates how much build it can absorb.
- `docker image ls` and `docker system df` on the main daemon fail with
  `blob sha256:438abc8a... not found` under `/srv/containerd/...`. The sketch already
  notes this and tracks the rebuild as task `9bc7abb8`.
- Not measured: the `ci` daemon's usage and storage driver. `sudo -iu ci docker ...`
  over a non-interactive ssh needs a password on picklelab.

## Decision

**Build each image in CI where its repo already runs CI, push to GHCR, and have the
main daemon only pull.** That means two builders:

- **GitHub Actions for images built from picklehome.** The repo is public and its
  `images` job in `.github/workflows/ci.yml` already builds all five of them
  (`scripts/check-images`). Actions minutes are free for public repos, the runners
  are native amd64 and much faster than the J3455, and the workflow's `GITHUB_TOKEN`
  can push to GHCR, so no personal token is involved.
- **Woodpecker on the rootless `ci` daemon for brineworks.** Brineworks already
  builds its server image there. Nothing found rules out this route, so the sketch's
  "short spike" mostly resolves on paper. The pilot measures the build time, and
  GitHub Actions stays the fallback if the J3455 can't keep up.

### Images to publish

| Image | Source repo | Builder | Notes |
|---|---|---|---|
| brineworks-server | brineworks (private) | Woodpecker, `ci` daemon | Pilot. Extends the existing `server-image` step |
| climate-auto-switch | picklehome (public) | GitHub Actions | Already built by `scripts/check-images` |
| obsidian-sync | picklehome (public) | GitHub Actions | Already built by `scripts/check-images` |
| openclaw-goplaces-node | picklehome (public) | GitHub Actions | Already built by `scripts/check-images` |
| open-webui | picklehome (public) | GitHub Actions | Already built by `scripts/check-images` |
| open-terminal | picklehome (public) | GitHub Actions | Already built by `scripts/check-images` |
| openclaw-gog-mcp | pickleclaw (private) | Not decided | The repo has no CI today |
| nikke | nikke-roster-scanner (private) | Not decided | The repo has no CI today |

### Why Woodpecker works without a new plugin

The pattern is already in use. [`brineworks/.woodpecker.yml`](https://github.com/technicalpickles/brineworks)
has a `server-image` step that runs `docker:27-cli` with `/run/user/2000/docker.sock`
bind-mounted from the rootless `ci` daemon and builds `server/Dockerfile` there. The
Woodpecker agent itself runs as uid 2000 with `DOCKER_HOST` pointing at that socket
(`homelab/services/woodpecker/compose.yaml`). A push step is the same step plus
`docker login` and `docker push`.

The Woodpecker `docker-buildx` plugin is not needed. On Woodpecker 3.x it must be
listed in `WOODPECKER_PLUGINS_PRIVILEGED`, which sits badly with a deliberately
unprivileged `ci` user. The step already bind-mounts the `ci` socket and relies on the
repo's "Volumes" trust, so no new trust is added.

### Why the `ci` store is the right place to build

- It is already separate from the main daemon: its data-root is `/srv/ci-docker`
  (`setup-rootless-ci-docker.sh`), the main store is `/srv/containerd`. Build layers and
  the BuildKit cache never touch the store that serves Brent.
- Per the options sketch, the `ci` store was intact on 2026-11-14 while the main store
  lost layers.
- Cost: an image built in `ci` and pulled into the main daemon exists twice on the
  host. After each push the step removes its tag from the `ci` store, and the build
  cache is capped (see below).

## Design

### Pipeline: picklehome on GitHub Actions

Two jobs in `.github/workflows/ci.yml`, split by event (PR #229, written 2026-11-15
and not yet run on `main`):

- `images` runs on pull requests only. It builds the images whose inputs changed
  (`scripts/check-images --changed-since HEAD^1`) and pushes nothing. A newer push to
  the same PR cancels the stale run.
- `publish-images` runs on pushes to `main` only, after `test` passes
  (`needs: test`). It logs in with `GITHUB_TOKEN` (`packages: write`), sets up buildx,
  and runs `scripts/check-images --push "$GITHUB_SHA"`, which pushes every image as
  `ghcr.io/technicalpickles/picklehome-<name>:<full-sha>`.

- `scripts/check-images` holds the name, context, Dockerfile and input paths for each
  image, so it stays the one list. Each `build` line names the repo paths the image
  reads. Keep them in step with the Dockerfile's `COPY` lines. A change to the script
  or `ci.yml` rebuilds all five.
- **Package names.** Every package is `ghcr.io/technicalpickles/picklehome-<name>`, so
  they group together under the account. The `<name>` in the image table above is the
  suffix. The first run published unprefixed names (`climate-auto-switch` and the
  rest). Those are superseded and can be deleted once nothing references them.
- Public images carry the `org.opencontainers.image.source` label so the package links
  to the repo, and every image carries `org.opencontainers.image.revision`.
- **A new package from this repo's Actions comes out public.** Probed 2026-11-15 with
  two empty images pushed by `GITHUB_TOKEN`, one with the source label and one without.
  Both were created public and linked to `picklehome`, so the label is not the cause.
  CI cannot change visibility, so it must never be the one that creates a package that
  has to be private. The packages in `PRIVATE` in `scripts/check-images`
  (`climate-auto-switch`, `obsidian-sync`) therefore have to exist already. To create
  one:
  1. Push an empty placeholder image to `ghcr.io/technicalpickles/picklehome-<name>`
     with a personal token that has `write:packages`. Nothing sensitive is in it, so
     a public moment is harmless.
  2. Confirm it is private (an anonymous pull returns 403). If not, set it private in
     the package's settings.
  3. In the package settings, give the `picklehome` repository write access under
     "Manage Actions access".

  Before pushing a `PRIVATE` image the script checks the package exists with an
  authenticated request (200 when it does, 404 `NAME_UNKNOWN` when it does not). If it
  does not, the script skips that image and the run ends red after the public images
  have been published. After a push it also checks the package is not anonymously
  pullable. These images are built without the source label as a precaution, so
  nothing links them to the public repo.
- **Visibility audit (2026-11-15).** The first `main` run (PR #229) published all five
  packages public and anonymously pullable, before anything had been checked. The
  design had called for confirming each image first, but nothing enforced that order.
  Rule for new images: state the visibility here and make sure the package starts that
  way before its first push, which for a private one means creating it by hand as
  described above. What was checked for the published amd64 images:
  - **Secrets.** None. No credentials in any image's `Env`. open-webui's `OPENAI_API_KEY`
    and `WEBUI_SECRET_KEY` are the upstream image's empty defaults.
  - **Repo content.** CI builds from a clean checkout, so the `COPY` lines (`climate/`,
    `pyproject.toml`, `uv.lock`, `entrypoint.sh`) carry only tracked files that are
    already public in this repo. The `OPENCLAW_NODE_*` values in goplaces-node are the
    compose service name and port, not secrets.
  - **Upstream terms and decisions.**
    - `picklehome-obsidian-sync` **private.** It installs `obsidian-headless`, which npm
      lists as `UNLICENSED`, so no right to redistribute is granted.
    - `picklehome-climate-auto-switch` **private.** The repo has no license, so its code
      is visible but not licensed for reuse. Adding one is tracked as a task.
    - `picklehome-open-terminal` public. Upstream is MIT. The upstream notice stays in
      the base layers, since we only add a layer.
    - `picklehome-open-webui` public, with a caveat. Upstream's license is BSD-3-style
      plus a clause that bars altering or removing "Open WebUI" branding above 50 users
      in 30 days. The wrapper only runs `chown` and a CA-certificate upgrade and leaves
      branding alone, so it should comply. Not checked: that the license text ships in
      the image layers (clause 2).
    - `picklehome-openclaw-goplaces-node` public. The bundled `openclaw` npm package and
      `goplaces` binary are both MIT.
  - Public gives a small benefit, since only public images skip the host pull token.
    That token (`pull-auth`) is needed for the private repos' images anyway, so when an
    image's status is in doubt, make it private.

### Timing and order (picklehome pipeline)

Decisions from working through what races what. All inferred from how GitHub Actions
and GHCR behave, none observed yet.

**Built in PR #229**

- **Tests before tags.** `publish-images` needs `test`, so a tag never exists for a
  commit CI rejected. It costs about 30s on `main` before the roughly 3 minute build.
  PRs build in parallel with the tests, since they publish nothing.
- **Main publishes every image on every commit.** The PR path filter does not apply
  here. If `main` skipped unchanged images, most commits would have no tag for most
  images, and a deploy waiting on its own SHA would hang. Unchanged images are layer
  cache hits and cost seconds.
- **No `concurrency` group on `main`.** GitHub drops older pending runs in a group even
  with `cancel-in-progress: false`. A dropped commit would never get tags. The one
  shared object is the `:buildcache` tag per package, where the last writer wins. A
  stale cache costs time, not correctness.
- **Per-PR concurrency with cancel.** Only the latest head of a PR needs an image.
- **Registry layer cache.** `main` builds with buildx and
  `--cache-from/--cache-to type=registry,ref=...:buildcache,mode=max`. This needs the
  docker-container builder, so `publish-images` sets up buildx. The `:buildcache` tag
  is cache, not a deploy target.

**Designed, not built** (tracked in taskwarrior, project `picklehome.homelab.disk-hygiene`)

- **Branch and PR images.** Push images from a same-repo PR when it carries a
  `publish-images` label, so a change can run on picklelab before merge. Tag
  `pr-<n>-<full head sha>`. Use `github.event.pull_request.head.sha`, because
  `github.sha` on a PR is a synthetic merge commit that matches nothing in `git log`.
  The `pr-` prefix keeps these out of the namespace a deploy waits on. Publish only the
  images the path filter picked. Read `:buildcache` but never write it, so a PR cannot
  poison the cache `main` builds from. Skip fork PRs, whose token is read-only and
  would fail at login.
- **Cleanup is a time-based sweep, not on PR close.** Deleting on close races a build
  still pushing (the tag reappears as an orphan). It also races a PR image deployed to
  picklelab and not yet replaced by `main`'s, and deleting that breaks a re-pull after
  image-store damage. A scheduled job deletes `pr-*` versions older than about 14 days
  and never touches other tags. GHCR has no retention setting of its own.
- **A PR image is not what `main` will build.** A merge creates a new SHA, so `main`
  rebuilds anyway. The first `main` build after a Dockerfile change is cold for the
  changed layers, once.

**Constraint on the deploy side**

- A compose file cannot pin the SHA of the commit that edits it, because the hash
  depends on the file contents. A pinned `image: ...:<sha>` always lags by at least one
  commit. Prefer injecting the SHA at deploy time (an env var such as `IMAGE_SHA` that
  compose interpolates), taken from the commit `deploy.sh` fast-forwarded to, which is
  what "Where the SHA comes from" below already says. Digest pins in the file remain an
  option for images that rarely change.
- **Decided: `deploy.sh` writes an untracked env file, the systemd unit loads it.**
  Checked against `open-webui` (2026-11-15): `deploy.sh` does not run compose. It runs
  `systemctl restart`, and the unit's `ExecStart` runs `docker compose up -d --build`
  under `op-run-dual.sh`. A SHA exported inside `deploy.sh` never reaches compose.
  So `deploy.sh` writes `IMAGE_SHA=$(git rev-parse HEAD)` to `$SERVICE_DIR/.env.image`
  (gitignored) before the restart, and the unit adds `EnvironmentFile=` for it. `op run`
  passes the inherited environment through to compose, which interpolates
  `ghcr.io/technicalpickles/picklehome-<name>:${IMAGE_SHA:?required}`. A restart outside
  `deploy.sh` (reboot, `systemctl restart`) reuses the last file, which is the right
  behavior: it comes back on the image that was last deployed.
  - Any compose command run by hand or by `deploy.sh` itself (the open-webui
    `exec` health check) must also see `IMAGE_SHA`, or `:?required` fails the parse. Add
    it to the placeholder list the way the secret vars are.
  - `open-terminal` lives in `open-webui`'s compose files, unit and `deploy.sh`, so the
    two images swap together in one PR.
  - Not yet checked: the other services' `deploy.sh`. Each swap re-checks its own.

### Pipeline: brineworks on Woodpecker

One step, on `main` pushes only, after the repo's tests:

```yaml
# Untested sketch. Shape follows brineworks' server-image step.
- name: image
  image: docker:27-cli
  volumes:
    - /run/user/2000/docker.sock:/var/run/docker.sock
  environment:
    GHCR_USER: technicalpickles
    GHCR_TOKEN:
      from_secret: ghcr_push_token
  when:
    - event: push
      branch: main
  commands:
    - echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GHCR_USER" --password-stdin
    - docker build --label org.opencontainers.image.source=<repo url>
        -t ghcr.io/technicalpickles/<name>:${CI_COMMIT_SHA} -f <Dockerfile> .
    - docker push ghcr.io/technicalpickles/<name>:${CI_COMMIT_SHA}
    - docker rmi ghcr.io/technicalpickles/<name>:${CI_COMMIT_SHA}
```

- **Tags.** The full commit SHA is the immutable tag. Hosts deploy by digest or by SHA,
  never `:latest`. A moving `main` tag is optional and only for humans.
- **Where the SHA comes from.** `deploy.sh` for an image built from this repo uses the
  commit it just fast-forwarded to. For another repo's image (brineworks, nikke,
  pickleclaw) the deploy resolves that repo's `origin/main` the way `checkout-ref.sh`
  already does.
- **Waiting for CI.** Deploy is no longer one synchronous step. `deploy.sh` polls for
  the tag (for example `docker manifest inspect ghcr.io/...:<sha>`) for a bounded time,
  then fails with a message that says "image not built yet", not a pull error.
- **The Brent window.** Per ADR 0003 the quiet check runs first. With a pull instead of
  a build between the check and the restart, the gap shrinks to a pull.
- **Compose.** `build:` is replaced by `image: ghcr.io/technicalpickles/<name>@sha256:...`
  or by an `IMAGE_SHA` interpolated at deploy time (see "Timing and order": a file
  cannot pin its own commit's SHA). brineworks-server's unit drops `--build` from `docker compose up -d`.
  Renovate is already configured in this repo and can bump pinned digests, but whether
  it handles digests in these compose files has not been checked.

### Auth

- **Push (GitHub Actions).** The workflow's `GITHUB_TOKEN` with `packages: write`. No
  stored secret.
- **Push (Woodpecker).** GHCR accepts classic personal access tokens only, with `write:packages`
  ([GitHub docs](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)).
  Stored as a Woodpecker secret `ghcr_push_token`. Restrict it to the `push` event and to
  the `docker:27-cli` image so no pull-request step can read it. A classic PAT cannot be
  limited to specific packages, so it is account-wide. A separate GitHub machine user
  that owns only the images would narrow that. Not decided.
- **Pull (host).** A `read:packages` token for the main (root) daemon only. `ci` never
  pulls the published images. Delivered through the 1Password path in the secrets
  design (`op run` or a credential helper) so it is not left as plaintext in
  `~/.docker/config.json`. That design is still unimplemented, so it blocks every
  private image (brineworks-server, gog-mcp, nikke) and may be the longest step.
  Public picklehome images do not need it.
- **Visibility.** Images from private repos stay private packages. An image with nothing
  sensitive in it could be public and then needs no pull token. Decide per image.

### Cache and cleanup in the `ci` store

- Remove the pushed tag after the push (in the sketch above), so the finished image is
  not kept in `ci`.
- Cap the BuildKit cache there, for example `docker builder prune --keep-storage <size>`
  run as `ci`. `docker-prune.sh` already runs `docker builder prune -f` as `ci`.
  Coordinate with PR #226, which changes the weekly prune on the main daemon.
- Exporting cache to the registry (`--cache-to type=registry`) probably needs a
  different builder than rootless dockerd's default one. Unverified, and not needed
  until a build is slow enough to hurt.

### Capacity

Builds compete with the test suites for 4 cores under `WOODPECKER_MAX_WORKFLOWS=2`
(the options sketch notes brineworks' 16-minute suite). The image step should run only
on `main` and depend on the tests, so it never competes with a pull-request run.

### Rollback

Deploy an older SHA or digest. The image is in GHCR and often still in the main store.
No source checkout and no build.

## Pilot: brineworks-server

First because it is Brent-critical, it was damaged, and its unit rebuilds on every start.

1. Add the push step to `brineworks/.woodpecker.yml` after `server-image`, on `main`.
   Create `ghcr_push_token` with the event and image restrictions.
2. Confirm the package appears in GHCR as private and is linked to the repo.
3. Create the read token, log the root daemon in, and `docker pull` the SHA by hand.
4. Switch `homelab/services/brineworks-server/compose.picklelab.yaml` to the pinned
   image, drop `--build` from the unit, add the wait-for-tag poll to `deploy.sh`.
5. Deploy through the normal `just deploy-brineworks-server` path.
6. Rollback drill: deploy the previous SHA and confirm it runs without any build.
7. Time the image step on the J3455, cold cache and warm, and note whether a `main`
   build queued behind it. If the step adds more than about 10 minutes to a `main`
   build, or regularly delays another repo's pipeline, move this image to GitHub
   Actions. That costs Actions minutes, because brineworks is private.

Done means the host has no `build:` for this service, a deploy pulls, the rollback
drill works, and the build time is recorded here. Then the rest, one service at a time
(order in the sketch).

## Rollout order

Each step names a slug so plans and commits can cite it.

1. **`brineworks-pilot`:** the pilot above.
2. **`picklehome-actions-publish`:** extend the `images` job and `scripts/check-images`
   to push on `main`. Then move each picklehome service from `build:` to a pinned image,
   one at a time, with a rollback drill on the first. Public packages make this
   independent of `pull-auth`, so it can run alongside the pilot.
3. **`pull-auth`:** the host's `read:packages` credential through 1Password. Blocks the
   pilot's step 3 and every private image.
4. **`private-repo-ci`:** pick a builder for pickleclaw (gog-mcp) and
   nikke-roster-scanner, neither of which has CI today, then add the build and push.

## Proxy or mirror: not now

The images we pull from upstream are pinned and pulled again only on a version bump.
The one likely heavy puller is Woodpecker's own CI steps (`python:3.11`, `node:22`,
`postgres:16-alpine`, `docker:27-cli`), and it is unchecked whether Woodpecker
re-pulls them each run. Docker Hub allows 200 pulls per 6 hours when logged in and
100 per IP when anonymous ([Docker docs](https://docs.docker.com/docker-hub/usage/));
no GHCR pull limit is documented.

Nothing measured shows a rate-limit problem. Cheaper steps come first, in order:

1. `docker login` to Docker Hub on the hosts.
2. Grep the Woodpecker agent logs for `toomanyrequests`.
3. Only if that shows real failures, or offline pulls matter, add a cache. The lightest
   candidate is a Zot instance with on-demand sync, or `docker-registry-proxy`. Both are
   compared in the research findings.

## Our own CI step images: not now

The question: should Woodpecker steps run on images we build and publish (a Python or
Node toolchain with dependencies preinstalled) instead of stock `python:3.11`,
`python:3.12` and `node:22` from Docker Hub?

Not now, for three reasons:

- **The expensive setup is already cached.** Brineworks keeps its venv in a per-branch
  named volume and caches pip and uv, so a prebuilt image would save only the
  `pip install uv` and pyrefly lines. pirpg, gilliam-ii and claudeofhours run `npm ci`
  or a `uv` install on stock images. That is not slow enough to justify an image.
- **Rate limits are unproven.** Woodpecker's docker backend is believed to pull a step
  image only when it is missing locally, unless the step sets `pull: true`. Unverified.
  If so, Docker Hub limits don't come into play. The proxy section's log grep settles it.
- **It costs upkeep.** Every base bump needs a rebuild pipeline. Mirroring Docker Hub
  images into GHCR also makes Renovate track our copy instead of upstream, which loses
  the update signal.

The cheaper way to get pinned step and base images is to have Renovate pin them by
digest (the `docker:pinDigests` preset). That also answers the Renovate open question
below for upstream images.

Revisit if a step gains setup that a volume can't cache (apt packages, Playwright
browsers, multi-minute installs), if three or more repos share a toolchain, or if the
logs show `toomanyrequests`. A related idea for later, outside this design: run the
tests inside the image about to ship, so CI tests exactly what gets deployed.

## Open questions

- **GHCR terms.** GitHub's docs say container storage and bandwidth are free "currently",
  with at least a month's notice before that changes. If that changes, option C or
  GitLab.com's registry is the fallback.
- **Token scope.** Machine user versus the personal account for the push token.
- **Woodpecker pull policy.** Does it re-pull step images every run?
- **Renovate.** Can it bump image digests in these compose files? For upstream images
  `docker:pinDigests` should cover it. Our own GHCR images are tagged by commit SHA, so
  the bump comes from the deploy rather than from Renovate.
- **Builder for pickleclaw and nikke-roster-scanner.** Both are private and have no CI.
  Woodpecker reuses the brineworks pattern. Actions costs minutes but doesn't load the
  J3455. Decide after the pilot's build timing is in.
- **Storage in the `ci` daemon.** Which graph driver, and how much does the cache
  grow between prunes. Needs someone with `sudo` on picklelab.
- **Pending evidence.** If damage turns up in a registry-pulled image or in the `ci`
  store, option B loses its main argument (the options sketch says the same).

## Rejected or deferred

- **Self-hosted registry on picklelab (option C).** Lives on the box it serves, so it is
  unavailable exactly when a re-pull is needed. Doubles disk use on the host.
- **GitHub-hosted Actions as the only builder.** Adopted for picklehome, where it
  already runs and is free. For the private repos it costs Actions minutes and adds a
  second CI system next to Woodpecker, so it stays the fallback there.
- **Building on the Mac.** It is arm64 and picklelab is amd64, so it needs emulated
  cross-builds.
- **Kaniko or Buildah plugins.** Exist for daemonless builds. Not needed because the
  `docker:cli` plus socket pattern already works here. Their maintenance status was not
  checked.
- **Synology as a registry or cache.** Off-box but not always on.
