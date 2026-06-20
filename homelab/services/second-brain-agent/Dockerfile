FROM ubuntu:24.04

ARG USERNAME=technicalpickles
ARG USER_UID=1000
ARG USER_GID=1000
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-server \
    git \
    curl \
    ca-certificates \
    jq \
    tmux \
    ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Node.js 22 (for Claude Code)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Claude Code (install latest; pin by replacing with @x.y.z when stability is needed)
RUN npm install -g @anthropic-ai/claude-code

# tmux session persistence plugins
RUN git clone --depth=1 https://github.com/tmux-plugins/tmux-resurrect /usr/local/lib/tmux-resurrect \
    && git clone --depth=1 https://github.com/tmux-plugins/tmux-continuum /usr/local/lib/tmux-continuum

# Create user matching host UID/GID. Ubuntu 24.04 ships with 'ubuntu' at UID 1000 — remove it first.
RUN userdel -r ubuntu 2>/dev/null || true \
    && groupadd --force --gid $USER_GID $USERNAME \
    && useradd --uid $USER_UID --gid $USER_GID -m -s /bin/bash $USERNAME

# SSH: key-only auth, persist GitHub's host key, remove default host keys (entrypoint writes them to volume)
RUN mkdir /var/run/sshd \
    && sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config \
    && ssh-keyscan github.com >> /etc/ssh/ssh_known_hosts 2>/dev/null \
    && rm -f /etc/ssh/ssh_host_*

# tmux config and entrypoint (build context is /opt/homelab root)
COPY homelab/services/second-brain-agent/tmux.conf /home/$USERNAME/.tmux.conf
RUN chown $USER_UID:$USER_GID /home/$USERNAME/.tmux.conf

COPY homelab/services/second-brain-agent/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 22
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
