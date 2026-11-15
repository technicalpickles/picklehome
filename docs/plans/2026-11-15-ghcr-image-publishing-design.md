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
- 4 cores (`nproc`) and 15GiB RAM.
- `docker image ls` and `docker system df` on the main daemon fail with
  `blob sha256:438abc8a... not found` under `/srv/containerd/...`. The sketch already
  notes this and tracks the rebuild as task `9bc7abb8`.
- Not measured: the `ci` daemon's usage and storage driver. `sudo -iu ci docker ...`
  over a non-interactive ssh needs a password on picklelab.

## Decision

**Build on picklelab in Woodpecker, on the rootless `ci` daemon, then push to GHCR.
The main daemon only pulls.**

GitHub-hosted Actions remains the fallback builder, but nothing found rules out the
Woodpecker route, so the sketch's "short spike" mostly resolves on paper.

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

### Pipeline, per image-producing repo

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
  (or `:<sha>`). brineworks-server's unit drops `--build` from `docker compose up -d`.
  Renovate is already configured in this repo and can bump pinned digests, but whether
  it handles digests in these compose files has not been checked.

### Auth

- **Push (CI).** GHCR accepts classic personal access tokens only, with `write:packages`
  ([GitHub docs](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)).
  Stored as a Woodpecker secret `ghcr_push_token`. Restrict it to the `push` event and to
  the `docker:27-cli` image so no pull-request step can read it. A classic PAT cannot be
  limited to specific packages, so it is account-wide. A separate GitHub machine user
  that owns only the images would narrow that. Not decided.
- **Pull (host).** A `read:packages` token for the main (root) daemon only. `ci` never
  pulls the published images. Delivered through the 1Password path in the secrets
  design (`op run` or a credential helper) so it is not left as plaintext in
  `~/.docker/config.json`. That design is still unimplemented, so this is a dependency.
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

Done means the host has no `build:` for this service, a deploy pulls, and the rollback
drill works. Then the rest, one service at a time (order in the sketch).

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

## Open questions

- **GHCR terms.** GitHub's docs say container storage and bandwidth are free "currently",
  with at least a month's notice before that changes. If that changes, option C or
  GitLab.com's registry is the fallback.
- **Token scope.** Machine user versus the personal account for the push token.
- **Woodpecker pull policy.** Does it re-pull step images every run?
- **Renovate.** Can it bump image digests in these compose files?
- **Storage in the `ci` daemon.** Which graph driver, and how much does the cache
  grow between prunes. Needs someone with `sudo` on picklelab.
- **Pending evidence.** If damage turns up in a registry-pulled image or in the `ci`
  store, option B loses its main argument (the options sketch says the same).

## Rejected or deferred

- **Self-hosted registry on picklelab (option C).** Lives on the box it serves, so it is
  unavailable exactly when a re-pull is needed. Doubles disk use on the host.
- **GitHub-hosted Actions as the builder.** Native amd64 and no push PAT
  (`GITHUB_TOKEN`), but a second CI system and Actions minutes on private repos. Kept
  as the fallback if Woodpecker builds prove too heavy for the box.
- **Building on the Mac.** It is arm64 and picklelab is amd64, so it needs emulated
  cross-builds.
- **Kaniko or Buildah plugins.** Exist for daemonless builds. Not needed because the
  `docker:cli` plus socket pattern already works here. Their maintenance status was not
  checked.
- **Synology as a registry or cache.** Off-box but not always on.
