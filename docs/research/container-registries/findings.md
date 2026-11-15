# Container registries: what we looked at (2026-11-15)

Research for [the GHCR publishing design](../../plans/2026-11-15-ghcr-image-publishing-design.md).
The question: where should picklelab's application images live, how do they get built,
and is a proxy or mirror worth running. This file keeps the options, techniques, and
numbers so the next person does not redo the search.

**Verification.** Claims were checked against official docs and repos on 2026-11-15
unless marked *unverified*. Pricing and limits change, so recheck before relying on a
number. No project states a RAM figure, so "lightweight" here means "single container,
few dependencies", not measured. Some vendor pages blocked fetches (403 or 429), and
those figures are marked.

## Two jobs a registry can do

- **Host our own images.** Push CI output, pull it back. This is the actual need.
- **Pull-through cache.** Fetch from Docker Hub, ghcr.io or quay.io once, serve locally.
  Helps with Docker Hub rate limits and with pulls while the internet is down.

Pull-through support is the main thing that separates the options.

## Self-hosted registries

- **[Zot](https://zotregistry.dev/)** does both jobs in one binary.
  - Pull-through through the sync extension. `onDemand: true` caches on first request.
    `registries` is an array, so several upstreams work in one instance
    ([mirroring docs](https://zotregistry.dev/v2.1.23/articles/mirroring/)).
  - Works against ghcr.io and quay.io, not only Docker Hub. The repo's
    [example config](https://raw.githubusercontent.com/project-zot/zot/main/examples/config-popular-registries.json)
    enables on-demand sync for Docker Hub, GitLab, ghcr.io, quay.io, gcr.io and
    registry.k8s.io, and the
    [blackbox tests](https://raw.githubusercontent.com/project-zot/zot/main/test/blackbox/sync_docker.bats)
    pull from quay.io and ghcr.io. No ghcr- or quay-specific bugs found, but the issue
    search was shallow.
  - Docker Hub needs on-demand only, not polled mirroring (Hub rate-limits and has no
    catalog listing), plus `http.compat: ["docker2s2"]`. The docs do not cover Hub login
    for rate limits.
  - UI in the full image (`zot`), none in `zot-minimal`. Auth: htpasswd (bcrypt), LDAP,
    OIDC, API keys, mTLS. Storage: local disk, S3-compatible, GCS, Azure. Inline GC on
    by default. Local dedupe uses BoltDB, so no replicas on local storage.
  - Footprint: no official RAM or image size. One user
    [reported](https://github.com/project-zot/zot/issues/3776) about 2GB RSS on a large
    server settling at 0.3GB after restart. The storage docs say Pi-class devices have
    very little RAM. A "~30MB" figure in a
    [Tekton proposal](https://github.com/tektoncd/plumbing/issues/3380) is an unverified
    estimate.
  - Running it: no official `docker run` or compose example. The install guide is
    systemd only, and the releases page only shows `docker pull ghcr.io/project-zot/zot:latest`.
- **[Distribution](https://distribution.github.io/distribution/)** (`registry:2`).
  Simplest thing that works.
  - Pull-through mirrors **one upstream per instance**
    ([mirror recipe](https://distribution.github.io/distribution/recipes/mirror/)). The
    config reference describes `remoteurl` as the "repository on Docker Hub"; whether
    other registries work is unclear. Upstream credentials are supported. Cached content
    expires after `proxy.ttl` (default 7 days) and needs `delete` enabled.
  - Auth is one provider at a time: `token`, `htpasswd` (bcrypt), `silly` (dev only) or
    `none` ([config](https://distribution.github.io/distribution/about/configuration/)).
    No UI in the docs (inferred from silence).
  - GC is manual (`registry garbage-collect`), with the registry read-only or stopped
    ([docs](https://distribution.github.io/distribution/about/garbage-collection/)).
- **[Harbor](https://goharbor.io/).** Scanning, replication, RBAC. Proxy cache supports
  Docker Hub, GHCR, Quay, ECR, ACR, GCR and Artifactory
  ([docs](https://goharbor.io/docs/main/administration/configure-proxy-cache/)).
  Minimum 2 CPU, 4GB RAM, 40GB disk; recommended 4 CPU, 8GB, 160GB
  ([prereqs](https://goharbor.io/docs/main/install-config/installation-prereqs/)).
  Too heavy here.
- **Forgejo and Gitea packages.** Built-in OCI registry, scoped to a user or org
  (`{registry}/{owner}/{image}`)
  ([Forgejo](https://forgejo.org/docs/latest/user/packages/container/),
  [Gitea](https://docs.gitea.com/usage/packages/container)). The docs are silent on
  multi-arch manifests, anonymous pull, RAM and pull-through, so those are unconfirmed,
  not absent. Only relevant if a forge is added.
- **GitLab self-hosted, Nexus, Artifactory, [Quay](https://github.com/quay/quay),
  [Pulp](https://github.com/pulp/pulp_container).** Heavy (Quay needs Postgres and
  Redis). Not researched in depth.
- **[Portus](https://github.com/SUSE/Portus).** Archived 2023, dead.

## Lightweight caches and UIs

- **[docker-registry-proxy](https://github.com/rpardini/docker-registry-proxy).** One
  nginx container (Alpine) that caches any registry. v0.8.0 dated 2026-10-22. Cache
  capped by `CACHE_MAX_SIZE` (default 32g). Upstream creds via `AUTH_REGISTRIES`.
  Catches: every client must trust its CA, private upstream images become available to
  anyone who can reach it, and default manifest caching makes some tags effectively
  immutable. No UI. This is the best pure cache found.
- **[Spegel](https://github.com/spegel-org/spegel)** and the
  **[k3s embedded mirror](https://docs.k3s.io/installation/registry-mirror)** (Spegel
  built in). A stateless peer-to-peer cache between nodes. Needs Kubernetes and
  containerd. Irrelevant on one host.
- **[Dragonfly](https://github.com/dragonflyoss/dragonfly)** and
  **[Kraken](https://github.com/uber/kraken).** P2P distribution for large clusters.
  Overkill.
- **[Joxit/docker-registry-ui](https://github.com/Joxit/docker-registry-ui).** A UI
  only, for registry v2/v3. Basic auth only. Deletion needs `DELETE_IMAGES=true` plus
  registry-side delete and CORS.
- *Unverified:* [Stashito](https://hub.docker.com/r/rcm7/stashito) (source repo returned
  404), [mcronce/oci-registry](https://github.com/mcronce/oci-registry),
  [aceeric/ociregistry](https://github.com/aceeric/ociregistry),
  [simple-registry](https://github.com/jlsalvador/simple-registry) (4 stars, no releases).

## Hosted registries that allow private images

| Service | Private on free? | Limits | Notes |
|---|---|---|---|
| [GHCR](https://docs.github.com/en/billing/concepts/product-billing/github-packages) | Yes | Container storage and bandwidth "currently free"; no pull limit documented | Classic PAT only (`read:packages`, `write:packages`). 10 GB per layer. Not a cache. A month's notice promised before a change. |
| [GitLab.com](https://docs.gitlab.com/user/packages/container_registry/) | Yes | Registry storage excluded from the 10 GiB project quota ([source](https://docs.gitlab.com/user/storage_usage_quotas/)); no registry cap documented | PAT, deploy token or group token. The [dependency proxy](https://docs.gitlab.com/user/packages/dependency_proxy/) caches Docker Hub only, free tier included. |
| [Docker Hub](https://docs.docker.com/docker-hub/usage/) | 1 private repo | 200 pulls per 6 hours logged in, 100 per IP anonymous | The pricing page says 100 pulls/hr, which conflicts with the usage page. Cannot mirror other registries. |
| [Oracle OCIR](https://docs.oracle.com/en-us/iaas/Content/Registry/Concepts/registryoverview.htm) | Yes | No charge for the service; 500 repos and 500 GB per region | Billed at Object Storage rates (secondary sources). Whether it counts against the Always Free allowance is unconfirmed. |
| [AWS ECR](https://aws.amazon.com/ecr/pricing/) | Time-limited | Private 500 MB, free 12 months for new accounts | ECR Public gives 50 GB always free, public only. |
| [Google Artifact Registry](https://cloud.google.com/artifact-registry/pricing) | Yes | 0.5 GB/month free, then about $0.10/GiB | From a search summary; direct fetch truncated. |
| [DigitalOcean](https://docs.digitalocean.com/products/container-registry/details/pricing/) | Yes | $0 starter: 500 MiB, 1 repo | Too small. |
| Quay.io | No (unverified) | | Red Hat page returned 403. |
| Azure ACR | No | Trial credit only | |
| Cloudsmith, JFrog, Scaleway, packagecloud, Fly.io, Cloudflare | Mostly no, or tied to their own platform | | [Cloudsmith](https://cloudsmith.com/pricing) free tier is 500 MB (snippet only). JFrog free SaaS looks closed to new sign-ups. packagecloud has no Docker repo type. Scaleway private is paid. Fly and Cloudflare registries serve only their own platforms. |
| Codeberg | Unverified | | Forgejo has a registry; could not confirm Codeberg enables it. |

Free S3-compatible storage could back a self-hosted Zot, but Zot with these backends
is untested: [Cloudflare R2](https://developers.cloudflare.com/r2/pricing/) (10 GB-month
free, free egress), [Backblaze B2](https://www.backblaze.com/cloud-storage/pricing)
(first 10 GB free), and Oracle Object Storage (20 GB, 10 TB egress per month).

## Docker client side

- Docker needs HTTPS to a registry unless it is in `127.0.0.0/8` or listed as insecure.
  The docs say the range, not the name "localhost"
  ([dockerd reference](https://docs.docker.com/reference/cli/dockerd/)).
- `registry-mirrors` in `daemon.json` mirrors **Docker Hub only**
  ([Docker docs](https://docs.docker.com/docker-hub/image-library/mirror/)). Whether
  that holds under the containerd image store (default on fresh Engine 29+ installs) is
  unclear in Docker's docs.
- containerd `hosts.toml` under `certs.d` works for any registry, with a `_default`
  catch-all ([containerd docs](https://github.com/containerd/containerd/blob/main/docs/hosts.md)).
  That is how ghcr or quay would be pointed at a cache.
- Distribution has one `remoteurl`, so several upstreams means one instance each.

## Build techniques (the part specific to our setup)

- **`docker:cli` step with the `ci` socket bind-mounted.** The pattern brineworks
  already uses. No plugin, no privileged container. Chosen. Details in the design.
- **Woodpecker `docker-buildx` plugin.** Exists
  ([Codeberg](https://codeberg.org/woodpecker-plugins/docker-buildx),
  [thegeeklab fork](https://github.com/thegeeklab/wp-docker-buildx)). On Woodpecker 3.x it
  must be listed in `WOODPECKER_PLUGINS_PRIVILEGED`. Woodpecker's docs say a fully
  rootless agent "may be possible" with a rootless daemon but is not supported.
- **Kaniko and Buildah plugins.** Listed on the [plugin page](https://woodpecker-ci.org/plugins)
  as unprivileged builders. Their maintenance status was not checked, and an attempt to
  confirm Kaniko's archival status found nothing either way.
- **GitHub-hosted Actions.** Native amd64 build, push with `GITHUB_TOKEN`. The Free plan
  includes about 2,000 minutes a month (third-party figure matching GitHub's billing
  table); arm64 runners in private repos arrived in
  [January 2026](https://github.blog/changelog/2026-01-29-arm64-standard-runners-are-now-available-in-private-repositories).
  A second CI system, so kept as a fallback.
- **Building on the Mac.** arm64 against amd64 picklelab, so it needs emulated
  cross-builds.
- **Registry cache export (`--cache-to type=registry`).** Probably needs a builder other
  than rootless dockerd's default. From memory, unverified.

## What we decided about proxies and mirrors

Not needed now. Upstream images are pinned, and nothing measured shows a rate-limit
problem. Docker Hub login on the hosts and a log grep for `toomanyrequests` come first.
Revisit if Woodpecker steps hit rate limits, or if offline pulls start to matter. The
lightest candidates then are Zot with on-demand sync or docker-registry-proxy.

## Still unknown

- Zot RAM and disk on a small box.
- Zot with R2 or B2 as the backend.
- Whether Forgejo or Gitea ship any pull-through cache.
- Whether GHCR's free container storage stays free.
- Whether Woodpecker re-pulls step images on every run.
