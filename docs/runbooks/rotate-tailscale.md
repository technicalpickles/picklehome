# Rotate Tailscale keys

Task `4f58f8a5`. See the [shared procedure](README.md#rotating-secrets) first.

Screens below were walked through in the admin console on 2026-11-10.

| Secret | 1Password | Used by | Action |
|---|---|---|---|
| `WOODPECKER_TS_AUTHKEY` | `picklehome/Woodpecker CI/ts_authkey` | `ts-woodpecker` sidecar (Woodpecker's tailnet identity and Funnel) | Mint a fresh key, store it. No deploy needed |
| `TAILSCALE_OAUTH_CLIENT_ID` / `_SECRET` | `picklehome/Tailscale API/client_id`, `client_secret` | `network/tailscale_audit.py` and the pickled-claude-plugins tailscale skill (both read-only) | Replace the OAuth credential |
| `TS_AUTHKEY` | none now | brineworks-agent sidecar (torn down) | Revoke only. Done 2026-11-10 |
| `SECOND_BRAIN_AGENT_TS_AUTHKEY` | none now | second-brain-agent sidecar (torn down) | Revoke only. Done 2026-11-10 |

## What an auth key is for

An auth key only lets a device join. `ts-woodpecker` keeps its node identity in
`/srv/data/woodpecker/ts-state` on picklelab (bind-mounted to `/var/lib/tailscale`),
so a running or restarted sidecar does not use the key. Checked 2026-11-10: the
stack restarted at 13:12 UTC and came back healthy, tagged `tag:ci`, with no node
key expiry, even though the Woodpecker auth key from the original build no longer
appears in the Keys list. Auth keys last 90 days at most and expired keys drop out
of the list, so it has almost certainly expired (it was created for the June build).

What follows from that:

- The exposed Woodpecker key is already dead. There is nothing to revoke.
- A key only matters if the state directory is lost and the sidecar has to join
  again. Because any key expires within 90 days, the one stored in 1Password
  will be expired by then anyway. Keep a recent one there so a rebuild works,
  and expect to mint a new one if you rebuild much later.
- Revoking a key never removes a device that already joined with it.
- Replacing the key does not need a deploy, so Woodpecker is not interrupted. The
  new value is picked up on the next deploy.

## Admin console map

Sign in at `https://login.tailscale.com/admin`, then the left nav, Settings:

| You want | Go to | Notes |
|---|---|---|
| Auth keys | Settings, Keys (`/admin/settings/keys`) | "Auth keys" list. Each row shows ID and Type. Expand the row (chevron) for Created, Expires, Description and Tags. `Revoke…` is per row. |
| API access tokens | Settings, Keys, same page, lower section | Short-lived tokens for the Tailscale API |
| OAuth clients | Settings, Trust credentials (`/admin/settings/trust-credentials`) | Not called "OAuth clients" any more. Columns: Client ID, Type, Scopes. `+ Credential` adds one, the row's `…` menu manages it. |

Expired keys drop out of the list, and only the Description tells keys apart, so
always set one. As of 2026-11-10 the list holds three keys that belong to other
projects (two dev keys, one laptop CI key tagged `tag:ci-agent`). Leave them.

## 1. Dead keys (done 2026-11-10)

The brineworks-agent and second-brain-agent keys were revoked from Settings,
Keys, `Revoke…` on the row. Nothing was deployed.

## 2. Mint a fresh Woodpecker key

Settings, Keys, `Generate auth key…`. The dialog has:

| Field | Set to |
|---|---|
| Description | `woodpecker ci rotated YYYY-MM-DD`, with the full date (this is how you find it later). Commas are not allowed in this field |
| Reusable | On |
| Expiration | Days until the key stops working, 1 to 90, default 90. Leave 90 |
| Ephemeral | Off. On would delete the node whenever it goes offline |
| Tags | On, then pick `tag:ci`. Tagging also disables node key expiry, which the sidecar relies on |

`Generate key` shows the value once. Copy it into the `ts_authkey` field of the
`Woodpecker CI` item in the 1Password app, then close the dialog. Do not paste it
anywhere else.

Nothing else is required. If you want the running container to use it right away,
`just deploy-woodpecker` restarts the stack. That kills any pipeline in flight and
drops webhooks during the gap (GitHub does not retry them), so only do it in a
quiet window, then redeliver any missed push from the repo's Settings, Webhooks,
Recent deliveries. After the restart check `just woodpecker-status` and push a
commit that triggers a pipeline.

## 3. Replace the OAuth credential

The one credential under Settings, Trust credentials today:

| Field | Value |
|---|---|
| Description | `pickled-claude-plugin tailscale` |
| Type and scope | OAuth, `all:read` |
| Created | 2026-09-12 |

It is read-only, and its name says who it was made for. Two things read it, both
through `TAILSCALE_OAUTH_CLIENT_ID` and `TAILSCALE_OAUTH_CLIENT_SECRET`:

- `network/tailscale_audit.py` in this repo.
- The tailscale plugin's skill in pickled-claude-plugins, which uses the same
  variables to query the policy file through the API.

Both get their values from `picklehome/Tailscale API` in 1Password, so replacing
the credential and updating that one item covers both. **Verify** that the Client
ID in that item matches the credential above before you delete anything.

Name every replacement the same way as the keys: the existing name, then
`rotated` and the full date, no commas. For example
`pickled-claude-plugin tailscale rotated 2026-11-10`. Keeping the prefix makes the
old and new ones easy to match up, and the date shows which is current.

1. Settings, Trust credentials. Confirm the existing credential's Client ID and
   scope (expand the row with the chevron).
2. `+ Credential`, choose OAuth, give it the read scope and the description above.
   **Verify** the dialog's exact fields and scope name the first time, and whether
   the description field rejects commas like the auth key one does.
3. Put the Client ID and secret in `picklehome/Tailscale API` in 1Password, using
   the app. The secret is shown once.
4. `just dotenv`, then run `network/tailscale_audit.py` and confirm it reads the
   policy file. Also confirm the plugin's token request still works.
5. Delete the old credential from its `...` menu.

## CLI alternatives

- **Listing keys.** The existing read-only credential can list auth keys through
  the API (`GET /api/v2/tailnet/-/keys`). **Verify** that `all:read` covers it.
  `network/tailscale_audit.py` is the place to add a keys listing, which would let
  you audit keys without opening the console.
- **Creating or revoking keys.** The API can do both, but only with a credential
  that can write keys. That is a stronger secret than the one you are rotating, and
  the point of the incident was keeping secrets out of command lines. For a task you
  do a few times a year, the console is the better tool. The `tailscale` CLI itself
  cannot mint auth keys.

## Done when

- Settings, Keys lists no key for brineworks-agent or second-brain-agent.
- A key described `woodpecker ci rotated YYYY-MM-DD` exists and is in 1Password.
- The old OAuth credential is deleted, the replacement is named `pickled-claude-plugin tailscale rotated YYYY-MM-DD`, and both the audit and the plugin still work.
- `task 4f58f8a5 done`.
