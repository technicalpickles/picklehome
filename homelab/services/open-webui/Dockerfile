# Wraps the pinned upstream image to fix a confirmed non-root permission bug:
# open-webui/open-webui#26662 (fix PR #26664 has since merged, but the static/
# permission errors still reproduce on v0.12.5, checked 2026-10-30).
# The stock image ships /app/backend/open_webui/static owned root:root,
# 0755/0644 (no group write), and rewrites its own bundled static assets
# (favicons, site.webmanifest, loader.js, user.png) into that dir on every
# boot. Any UID other than 0 fails those writes with ~19 "Permission denied"
# errors per boot -- the UI still loads from the pre-existing files, but it's
# alarming log noise and blocks custom static/branding overrides. Chown once
# at build time instead of fighting it at runtime, or giving up and running
# as root (which the repo's container-user-model convention in
# homelab/services/README.md rules out for anything writing to /srv/data).
#
# Drop this file and switch compose.yaml back to pulling
# ghcr.io/open-webui/open-webui directly once the upstream fix ships and the
# pin is bumped past it.
# USE_SLIM=true drops embedding/whisper models (~3-4GB savings)
ARG USE_SLIM=true
FROM ghcr.io/open-webui/open-webui:v0.12.5
USER root
RUN chown -R 1000:1000 /app/backend/open_webui/static

# eMudhra intermediate-CA compromise (2026-10-20, https://emudhra.we-have-a-problem.com).
# The upstream image's system CA package and its pip certifi both still trust the
# compromised chain, and requests/aiohttp/httpx read certifi while curl/urllib read
# the system store, so both need fixing. Needs Debian ca-certificates >=
# 20250419~deb12u2 and certifi >= 2026.10.19. Drop this layer once the pinned
# upstream tag ships both.
RUN apt-get update \
 && apt-get install -y --no-install-recommends --only-upgrade ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && python -m pip install --no-cache-dir -U 'certifi>=2026.10.19'

USER 1000:1000
