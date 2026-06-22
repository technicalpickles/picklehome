# Auto-attach interactive SSH/mosh logins to the persistent `main` tmux session.
# Lands a phone (or laptop) straight in the running session instead of a bare shell.
#
# Guards, in order:
#   case $- in *i*  -- interactive shells only. Skips the boot-time `su -c "tmux
#                      new-session -d"` and any `ssh host cmd`, which are non-interactive.
#   -z $TMUX        -- don't recurse: panes inside tmux already have TMUX set.
#   -t 1            -- stdout is a real tty.
# Detaching (or tmux failing) returns here and the login shell continues to a normal
# prompt, so this is non-destructive: it never logs you out, it just defaults you in.
case "$-" in
  *i*)
    if [ -z "${TMUX:-}" ] && [ -t 1 ] && command -v tmux >/dev/null 2>&1; then
      tmux attach-session -t main 2>/dev/null \
        || tmux new-session -s main -c /vault
    fi
    ;;
esac
