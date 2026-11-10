# Rotate Tailscale keys

Task `4f58f8a5`. See the [shared procedure](README.md#rotating-secrets) first.

| Secret | 1Password | Used by | Action |
|---|---|---|---|
| `WOODPECKER_TS_AUTHKEY` | `picklehome/Woodpecker CI/ts_authkey` | `ts-woodpecker` sidecar (Woodpecker's tailnet identity and Funnel) | Rotate and redeploy |
| `TAILSCALE_OAUTH_CLIENT_ID` / `_SECRET` | `picklehome/Tailscale API/client_id`, `client_secret` | `network/tailscale_audit.py` (read-only audit) | Replace the OAuth client |
| `TS_AUTHKEY` | none now | brineworks-agent sidecar (torn down) | Revoke only |
| `SECOND_BRAIN_AGENT_TS_AUTHKEY` | none now | second-brain-agent sidecar (torn down) | Revoke only |

Revoking an auth key does not remove a node that already joined with it. The
sidecar keeps its node identity in `TS_STATE_DIR`. A key is only needed to
join, so the risk of leaving the old one live is someone else joining the
tailnet with it.

## 1. Revoke the dead keys

Tailscale admin console, Settings, Keys. Find the keys for brineworks-agent and
second-brain-agent (the auth keys, not the machines) and revoke them. Nothing to
deploy. If you can't tell which is which, the creation dates and the `tag:`
they carry narrow it down. Check that no machine you still use shows up as
created by that key before revoking.

## 2. Rotate the Woodpecker auth key

1. Admin console, Settings, Keys, Generate auth key. Reusable, tag `tag:ci`,
   expiry as long as allowed. Auth keys expire (90 days at most), but only
   matters if the sidecar has to rejoin.
2. Put it in the `ts_authkey` field of `Woodpecker CI` in 1Password (app, not
   `op`).
3. `just deploy-woodpecker`
4. Check: `just woodpecker-status` shows `ts-woodpecker` up, and
   `https://woodpecker.tail2023b7.ts.net` loads from a tailnet device.
5. Check the webhook path: push an empty commit to a repo with a Woodpecker
   pipeline and confirm a pipeline starts. The Funnel is how GitHub reaches
   Woodpecker.
6. Revoke the old key in the admin console.

## 3. Replace the OAuth client

1. Before anything, open the old OAuth client and note its scopes. The audit is
   read-only, so it should need nothing writable. **Verify** against the header
   of `network/tailscale_audit.py`.
2. Admin console, Settings, OAuth clients, Generate with the same scopes.
3. Put the id and secret into `picklehome/Tailscale API` in 1Password.
4. `just dotenv` to refresh the local `.env`, then run `network/tailscale_audit.py`
   and confirm it reads the policy file.
5. Delete the old OAuth client.

## Done when

- The two dead keys and the old Woodpecker key show as revoked.
- The old OAuth client is deleted.
- Woodpecker runs a pipeline from a fresh push.
- `task 4f58f8a5 done`.
