@README.md

## When exposing a new service over Tailscale

Standing up a new `svc:<name>` Service (admin console → `serve --service=` → restart `tailscaled` → approve → validate from a different node) has a specific required order that's easy to get wrong on a first deploy. Use the `tailscale-cli` skill for that sequence and for debugging `serve status`/Services once it's up. Use the `tailscale-serve-patterns` skill when deciding whether to bind loopback + `serve` (the default here, see README.md) vs. binding directly to the tailnet interface, and for identity-header auth (`Tailscale-User-Login`) implications.

## When adding a new service with bind mounts

Before writing any compose or Dockerfile, answer:

1. **What uid will the process run as?** Check the base image's default (many images default to root). If it needs to write to `/srv/data/`, it must not run as root.
2. **Does any other service read or write the same host path?** If yes, both must use the same uid. Set `user: "uid:gid"` in compose for both.
3. **Do existing host files have the right ownership?** Add `sudo chown -R uid:gid /srv/data/<service>` to `deploy.sh` (after `mkdir -p`, before `docker compose up`).

For the implementation choices, see the "Container user model and bind-mount ownership" section in README.md — it covers `user:` vs Dockerfile, explicit uid vs named user, and the cross-service sharing pattern.

## When changing a service's uid

If an existing service gains a new `user:` or changes uid:

1. Update `deploy.sh` to chown the data directory to the new uid — this runs on next deploy and fixes existing files
2. If another service shares a volume with this one, update that service's deploy.sh too
3. If the container writes the mount at startup (entrypoint), gate any recovery chown on `stat -c %u` rather than running unconditionally
