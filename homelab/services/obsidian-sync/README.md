# obsidian-sync

Headless [Obsidian Sync](https://obsidian.md/sync) clients that keep vaults synced to
picklelab so agents on the host can read and write them. Each vault runs as its own
long-lived container continuously syncing against Obsidian's cloud.

## Architecture

- **Image:** `node:22-alpine` with [`obsidian-headless`](https://www.npmjs.com/package/obsidian-headless)
  installed globally; the container runs `ob sync --continuous`.
- **One container per vault.** `compose.yaml` defines two services, `rpg` and
  `pickled-knowledge`, each with two volumes:
  - `/root/.config`: the vault's Obsidian config + sync credentials (per-vault, so logins
    don't collide)
  - `/vault`: the synced vault files
- **On-host data:** `compose.picklelab.yaml` maps those volumes to
  `/srv/data/obsidian-sync/config/<vault>` and `/srv/data/obsidian-sync/vaults/<vault>`.
- **Service unit:** `obsidian-sync.service` is a `RemainAfterExit` oneshot that does
  `docker compose up -d` (and `down` on stop), so both vault containers come back after a reboot.
- **Auth:** handled interactively per vault (see below), not via `.env`, so there are no env
  vars for this service.
- **Backup:** not backed up. The Obsidian cloud is the source of truth; the host copy is a
  replica.

## First-time setup (from Mac)

```bash
just deploy-obsidian-sync   # create data dirs, build image, install + start the service unit
```

Then do the one-time interactive auth per vault (persisted in that vault's config volume):

```bash
just obsidian-sync-exec rpg login        # account login
just obsidian-sync-exec rpg sync-setup   # pick the remote vault, set the e2ee password
```

`ob sync-setup` is the step that matters: it caches the derived `encryptionKey` + `encryptionSalt`
in `sync/<vault-id>/config.json`, after which `ob sync --continuous` runs unattended. Each vault
is fully independent, so repeat for `pickled-knowledge` (or any other vault).

`obsidian-sync-exec <vault> <args>` runs the `ob` CLI inside that vault's container
(`docker exec -it obsidian-sync-<vault>-1 ob <args>`).

## Operations

```bash
just obsidian-sync-status                       # systemd unit status
just obsidian-sync-logs                          # last 50 lines (both containers)
just obsidian-sync-logs-follow                   # tail -f
just obsidian-sync-exec rpg sync-status          # sync state for one vault
just deploy-obsidian-sync                        # redeploy (git pull + rebuild + restart)
```

## Adding a vault

1. Add a new service block (and its two volumes) to `compose.yaml`
2. Add the on-host volume mounts to `compose.picklelab.yaml`
3. Add the data dirs to the `mkdir -p` list in `deploy.sh`
4. `just deploy-obsidian-sync`, then `just obsidian-sync-exec <vault> login` + `sync-setup`
