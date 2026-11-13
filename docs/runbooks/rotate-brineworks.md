# Rotate Brineworks secrets

Rotate these on a schedule, and whenever one leaks. See the [shared procedure](README.md#rotating-secrets) first.

| Secret | 1Password (`picklehome/Brineworks Server`) | Used by | Action |
|---|---|---|---|
| `BRINEWORKS_API_KEY` | `api_key` | brineworks-server | New value, redeploy server |
| `BRINEWORKS_OPENCLAW_MCP_KEY` and `BRINEWORKS_MCP_TOKEN` | `openclaw_mcp_key` (one field, two names) | server checks it, openclaw sends it | New value, redeploy both |
| `BRINEWORKS_DB_PASSWORD` | `db_password` | Postgres role plus the server | Change in the database too |
| `BRINEWORKS_SERVER_KEYRING_PASSWORD` | `Brineworks Server Keyring / password` | encrypts the stored Gmail tokens | Not a plain swap. See [restic and keyrings](rotate-restic-and-keyrings.md) |

The keyring password is deliberately left out here, because changing the value
without re-encrypting what it protects locks the data.

## Before you start

`just openclaw-quiet`. Both deploys refuse while Brent is active, and the
restart kills a turn in progress.

## API key

1. Find who calls the server with `BRINEWORKS_API_KEY`. `git grep
   BRINEWORKS_API_KEY` for the repo side, and check the `bw` CLI config on your
   Mac, which may hold a copy. **Verify** the full consumer list in the
   brineworks repo, not only here.
2. Generate with `openssl rand -base64 32` and put it in `api_key`.
3. `just deploy-brineworks-server`
4. Update each client you found, then check each one authenticates.

## MCP key (server and openclaw share it)

The server reads it as the secret for the `openclaw` label in
`BRINEWORKS_API_KEYS`; openclaw sends it in an Authorization header. Until both
sides have the new value, openclaw's brineworks calls fail with an auth error,
so do the two deploys back to back.

1. Generate with `openssl rand -base64 32` and put it in `openclaw_mcp_key`.
2. `just deploy-brineworks-server`, then `just deploy-openclaw` straight after.
   If you are rotating the OpenClaw secrets in the same session, this deploy
   covers both.
3. Check: ask Brent for something that needs brineworks (a task or email lookup).
   An MCP "not connected" or 401 means one side still has the old key.

## Database password

Postgres only reads `POSTGRES_PASSWORD` when it first creates an empty data
directory. Changing the env var alone leaves the real role on the old password,
and the server then fails to connect. Change both, in this order:

1. Take a backup first: `just backup-now`, then `just backup-snapshots` to
   confirm a fresh snapshot, which includes the `pg_dumpall.sql` dump.
2. Generate the new password with `openssl rand -base64 32`. Check the character
   set is safe if the password is ever placed inside a URL; Bugsink needed hex
   for that reason, and this service's server may have the same limit. **Verify**
   how `compose.yaml` and the server use it.
3. Change it in the database. The role name is `POSTGRES_USER` in the compose
   file. Run the `ALTER ROLE ... PASSWORD` from a `psql` session inside the db
   container, typing the value into the prompt, not on a command line.
4. Put the same value in `db_password` in 1Password.
5. `just deploy-brineworks-server`
6. Check `/health`, then a real read through Brent.

If the deploy fails to connect, the 1Password value and the role disagree.
Put the old password back in the role (or in 1Password), redeploy, and retry.

## Done when

- Server health is green and Brent can read brineworks.
- Anything that held the old API key has the new one.
