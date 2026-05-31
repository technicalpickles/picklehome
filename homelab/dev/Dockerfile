FROM ubuntu:24.04

ARG USERNAME=technicalpickles
ARG USER_UID=1000
ARG USER_GID=1000
# Avoid interactive prompts during install
ENV DEBIAN_FRONTEND=noninteractive

# Restore full system (Ubuntu minimal strips docs, man pages, etc.)
RUN yes | unminimize

# Base tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server \
    git \
    curl \
    ca-certificates \
    jq \
    sudo \
    unzip \
    software-properties-common \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Fish shell
RUN apt-add-repository -y ppa:fish-shell/release-4 \
    && apt-get update && apt-get install -y --no-install-recommends fish \
    && rm -rf /var/lib/apt/lists/*

# Neovim (latest stable from GitHub release, PPAs lag behind)
RUN curl -fsSL https://github.com/neovim/neovim/releases/latest/download/nvim-linux-x86_64.tar.gz \
    | tar xz -C /opt \
    && ln -sf /opt/nvim-linux-x86_64/bin/nvim /usr/local/bin/nvim

# CLI tools available via apt
RUN apt-get update && apt-get install -y --no-install-recommends \
    bat \
    fd-find \
    fzf \
    direnv \
    tmux \
    && rm -rf /var/lib/apt/lists/* \
    # Ubuntu names these differently, add symlinks for expected names
    && ln -sf /usr/bin/batcat /usr/local/bin/bat \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd

# Docker CLI (not the daemon, talks to host via socket)
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu noble stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends \
    docker-ce-cli \
    docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# Node.js (for Claude Code)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# uv (Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Standalone tool installs
RUN curl -fsSL https://just.systems/install.sh | bash -s -- --to /usr/local/bin \
    && curl -fsSL https://starship.rs/install.sh | sh -s -- -y \
    && curl -fsSL https://mise.run | sh \
    && mv /root/.local/bin/mise /usr/local/bin/mise

# GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# eza (ls replacement, not in Ubuntu 24.04 apt)
RUN curl -fsSL https://raw.githubusercontent.com/eza-community/eza/main/deb.asc \
    | gpg --dearmor -o /usr/share/keyrings/eza-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/eza-archive-keyring.gpg] http://deb.gierens.de stable main" \
    > /etc/apt/sources.list.d/eza.list \
    && apt-get update && apt-get install -y --no-install-recommends eza \
    && rm -rf /var/lib/apt/lists/*

# git-delta (diff viewer)
RUN DELTA_VERSION=0.18.2 \
    && curl -fsSL "https://github.com/dandavison/delta/releases/download/${DELTA_VERSION}/git-delta_${DELTA_VERSION}_amd64.deb" -o /tmp/delta.deb \
    && dpkg -i /tmp/delta.deb && rm /tmp/delta.deb

# Create user matching host UID/GID, with fish as default shell
# Ubuntu 24.04 ships with a 'ubuntu' user at UID 1000, remove it first
RUN userdel -r ubuntu 2>/dev/null || true \
    && groupadd --force --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m -s /usr/bin/fish $USERNAME \
    && echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/$USERNAME

# Add user to docker group, GID must match host for socket access
ARG DOCKER_GID=990
RUN groupadd --gid $DOCKER_GID docker 2>/dev/null; usermod -aG docker $USERNAME

# SSH server setup + GitHub host key
# Remove generated host keys, entrypoint generates them into a persistent volume
RUN mkdir /var/run/sshd \
    && sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config \
    && ssh-keyscan github.com >> /etc/ssh/ssh_known_hosts 2>/dev/null \
    && rm -f /etc/ssh/ssh_host_*


COPY entrypoint.sh /usr/local/bin/entrypoint.sh

EXPOSE 22

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
