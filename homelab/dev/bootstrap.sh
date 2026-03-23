#!/usr/bin/env bash
# Run once after first SSH into the dev container.
# Requires SSH agent forwarding for git clone.
set -euo pipefail

DOTFILES_DIR="$HOME/github.com/technicalpickles/dotfiles"
LAZYVIM_DIR="$HOME/github.com/technicalpickles/pickled-lazyvim"

echo "==> Configuring git for container environment"
# Rewrite HTTPS to SSH for our repos only — leave public repos (fisher plugins etc.) on HTTPS
git config --global url."git@github.com:technicalpickles/".insteadOf "https://github.com/technicalpickles/"
# Trust bind-mounted repos with different ownership
git config --global --add safe.directory "*"

echo "==> Cloning dotfiles"
if [ -d "$DOTFILES_DIR" ]; then
  echo "    Already exists, pulling latest"
  git -C "$DOTFILES_DIR" pull
else
  mkdir -p "$(dirname "$DOTFILES_DIR")"
  git clone git@github.com:technicalpickles/dotfiles.git "$DOTFILES_DIR"
fi

echo "==> Running dotfiles install"
cd "$DOTFILES_DIR"
DOTPICKLES_ROLE=personal ./install.sh || true

# Override 1Password IdentityAgent — use forwarded SSH agent in containers
# 00- prefix ensures this is matched before the dotfiles auth config
mkdir -p ~/.ssh/config.d
cat > ~/.ssh/config.d/00-container <<'SSH'
# Use forwarded SSH agent, not 1Password (which isn't available in containers)
Host *
  IdentityAgent SSH_AUTH_SOCK
SSH

echo "==> Cloning pickled-lazyvim (nvim config)"
if [ -d "$LAZYVIM_DIR" ]; then
  echo "    Already exists, pulling latest"
  git -C "$LAZYVIM_DIR" pull
else
  mkdir -p "$(dirname "$LAZYVIM_DIR")"
  git clone git@github.com:technicalpickles/pickled-lazyvim.git "$LAZYVIM_DIR"
fi
ln -sf "$LAZYVIM_DIR" "$HOME/.config/nvim"

echo ""
echo "Done! Reconnect to pick up all config."
