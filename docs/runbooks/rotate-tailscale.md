# Rotate Tailscale credentials

Two Tailscale credentials live in 1Password. Rotate them on a schedule, and any
time either one leaks. See the [shared procedure](README.md#rotating-secrets) first.

| Credential | 1Password | Used by | Rotation |
|---|---|---|---|
| Woodpecker auth key | `picklehome/Woodpecker CI/ts_authkey` | `ts-woodpecker` sidecar (Woodpecker's tailnet identity and Funnel) | Mint a fresh key, store it. No deploy needed |
| API OAuth credential | `picklehome/Tailscale API/client_id`, `client_secret` | `network/tailscale_audit.py` and the pickled-claude-plugins tailscale skill (both read-only) | Replace the credential, update the item, revoke the old one |

Both are named with the date they were made, so the newest is always obvious:

- Auth key description: `woodpecker ci rotated YYYY-MM-DD`
- OAuth credential description: `pickled-claude-plugin tailscale rotated YYYY-MM-DD`

Use the full date and no commas. The auth key description field rejects commas, so
assume the credential's does too.

## What an auth key is for

An auth key only lets a device join the tailnet. `ts-woodpecker` keeps its node
identity in `/srv/data/woodpecker/ts-state` on picklelab (bind-mounted to
`/var/lib/tailscale`), so a running or restarted sidecar does not use the key.
You can confirm the mount with `docker inspect` on the `ts-woodpecker` container.

What follows from that:

- Replacing the stored key needs no deploy and does not interrupt Woodpecker. The
  new value is picked up on the next deploy.
- The key matters only if the state directory is lost and the sidecar has to join
  again. Auth keys last 90 days at most, so one stored in 1Password for long enough
  will have expired by then. Rotating on a schedule keeps a usable one there.
- Revoking a key never removes a device that already joined with it.
- A key stays valid until it expires or is revoked, so revoke the previous one once
  the new one is stored.

## Admin console map

Sign in at `https://login.tailscale.com/admin`, then the left nav, Settings:

| You want | Go to | Notes |
|---|---|---|
| Auth keys | Settings, Keys (`/admin/settings/keys`) | "Auth keys" list. Each row shows ID and Type. Expand the row (chevron) for Created, Expires, Description and Tags. `Revoke…` is per row. |
| API access tokens | Settings, Keys, same page, lower section | Short-lived tokens for the Tailscale API |
| OAuth credentials | Settings, Trust credentials (`/admin/settings/trust-credentials`) | Columns: Client ID, Type, Scopes. Expand a row for Description, Created and Created by. `+ Credential` adds one, the row's `...` menu manages it. Removed credentials stay listed, marked `Revoked`. |

Expired keys drop out of the list, and only the Description tells keys apart. Other
keys on the page belong to other things, so only touch ones whose description you
recognise.

## 1. Rotate the Woodpecker auth key

Settings, Keys, `Generate auth key…`. The dialog has:

| Field | Set to |
|---|---|
| Description | `woodpecker ci rotated YYYY-MM-DD` |
| Reusable | On |
| Expiration | Days until the key stops working, 1 to 90, default 90. Leave 90 |
| Ephemeral | Off. On would delete the node whenever it goes offline |
| Tags | On, then pick `tag:ci`. Tagging also disables node key expiry, which the sidecar relies on |

`Generate key` shows the value once. Copy it into the `ts_authkey` field of the
`Woodpecker CI` item in the 1Password app, then close the dialog. Do not paste it
anywhere else.

Then revoke the previous `woodpecker ci rotated …` key: Settings, Keys, expand the
older row to check its description, `Revoke…`.

Nothing needs deploying. If you want the running container to read the new key
right away, `just deploy-woodpecker` restarts the stack, which interrupts CI. Follow
[Redeploying Woodpecker](woodpecker-redeploy.md) for what to check before and what to
recover after.

## 2. Replace the OAuth credential

The credential is read-only, with the single scope `all:read`. Two things read it,
both through `TAILSCALE_OAUTH_CLIENT_ID` and `TAILSCALE_OAUTH_CLIENT_SECRET`:

- `network/tailscale_audit.py` in this repo.
- The tailscale plugin's skill in pickled-claude-plugins, which uses the same
  variables to query the policy file through the API.

Both get their values from `picklehome/Tailscale API` in 1Password, so replacing the
credential and updating that one item covers both.

1. Settings, Trust credentials. Expand the current credential and note its Client ID
   and scope. Check the Client ID matches the `client_id` in the 1Password item
   before you delete anything.
2. `+ Credential`, choose OAuth, give it the same read scope and the description
   `pickled-claude-plugin tailscale rotated YYYY-MM-DD`. **Verify** the dialog's
   exact fields and scope name the first time.
3. Put the Client ID and secret in `picklehome/Tailscale API` in 1Password, using
   the app. The secret is shown once.
4. `just dotenv`, then run `network/tailscale_audit.py` and confirm it reads the
   policy file. Also confirm the plugin's token request still works.
5. Remove the previous credential from its `...` menu. The console keeps it listed with a
   `Revoked` label, so a `Revoked` row means it is dead, not that removal failed.

## CLI alternatives

- **Listing keys.** The read-only credential can probably list auth keys through the
  API (`GET /api/v2/tailnet/-/keys`). **Verify** that `all:read` covers it.
  `network/tailscale_audit.py` is the place to add a keys listing, which would let
  you audit keys without opening the console.
- **Creating or revoking keys.** The API can do both, but only with a credential
  that can write keys. That is a stronger secret than the one you are rotating, and
  the point of rotating is keeping secrets out of command lines. For a task you do a
  few times a year, the console is the better tool. The `tailscale` CLI itself cannot
  mint auth keys.

## Done when

- One `woodpecker ci rotated …` key is listed, the newest, and it is in 1Password.
- One `pickled-claude-plugin tailscale rotated …` credential is listed, the newest,
  and the audit and the plugin both work with it.
- The previous key and credential are revoked or deleted.
