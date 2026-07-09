# syntax=docker/dockerfile:1
FROM node:24-bookworm

ARG TARGETARCH
ARG GOPLACES_VERSION=0.4.4
ARG OPENCLAW_VERSION=2026.6.11

# goplaces: Google Places CLI, baked in at build time (installing at container
# runtime is a trap -- anything installed after build is lost on restart).
# TARGETARCH is populated automatically by BuildKit from the build host's own
# platform -- Go's release-asset arch names (amd64/arm64) match Docker's
# TARGETARCH values exactly, so the same Dockerfile builds correctly on both
# picklelab (amd64) and a Mac dev checkout (arm64) with no edits.
RUN curl -fsSL "https://github.com/openclaw/goplaces/releases/download/v${GOPLACES_VERSION}/goplaces_${GOPLACES_VERSION}_linux_${TARGETARCH}.tar.gz" \
  | tar -xzO goplaces > /usr/local/bin/goplaces \
  && chmod +x /usr/local/bin/goplaces

RUN npm install -g "openclaw@${OPENCLAW_VERSION}"

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Connects to the openclaw gateway service over compose's default network --
# plain service-name DNS, no Tailscale/lan-bind puzzle like the dev-VM version
# needed (gateway.bind is already "lan" here, and both services share one
# compose project's default network).
ENV OPENCLAW_NODE_HOST=openclaw
ENV OPENCLAW_NODE_PORT=18789
ENV OPENCLAW_NODE_DISPLAY_NAME=goplaces-node

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
