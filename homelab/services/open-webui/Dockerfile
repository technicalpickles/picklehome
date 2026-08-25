# Wraps the pinned upstream image to fix a confirmed non-root permission bug:
# open-webui/open-webui#26662 (fix PR #26664 open, not merged, as of v0.10.2).
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
FROM ghcr.io/open-webui/open-webui:v0.10.2
USER root
RUN chown -R 1000:1000 /app/backend/open_webui/static
USER 1000:1000
