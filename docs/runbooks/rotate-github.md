# Rotate GitHub credentials

Rotate these on a schedule, and whenever one leaks. See the [shared procedure](README.md#rotating-secrets) first.

| Secret | 1Password | Used by | Action |
|---|---|---|---|
| `OPENCLAW_WORKSPACE_GITHUB_TOKEN` (PAT) | `picklehome/OpenClaw Workspace/github_pat` | openclaw, to reach the workspace repo | Replace the PAT, `just deploy-openclaw` |
| `WOODPECKER_GITHUB_CLIENT` / `_SECRET` | `picklehome/Woodpecker CI/github_client`, `github_secret` | Woodpecker's GitHub OAuth app login | New client secret, `just deploy-woodpecker` |
| `OPENCLAW_PICKLECLAW_DEPLOY_KEY_B64` | `picklehome/OpenClaw Pickleclaw Deploy Key/deploy_key_b64` | `deploy.sh`, clones `pickleclaw@main` (read-only) | New key pair, `just deploy-openclaw` |

## 1. Woodpecker OAuth app

GitHub OAuth apps can hold two client secrets at once, so this has no downtime.

1. GitHub, Settings, Developer settings, OAuth Apps, the Woodpecker app,
   Generate a new client secret. Don't delete the old one yet.
2. Put it in `github_secret` on `Woodpecker CI` in 1Password. The client id does
   not change.
3. `just deploy-woodpecker`, following [Redeploying Woodpecker](woodpecker-redeploy.md)
4. Check: sign out of Woodpecker and sign back in with GitHub. Then push an
   empty commit to a repo with a pipeline and confirm it runs.
5. Delete the old client secret on the OAuth app.

`WOODPECKER_AGENT_SECRET` is a separate, internal secret shared by the server and
the agent, so it is not part of this flow. Rotate it on its own: update
`agent_secret` in 1Password and `just deploy-woodpecker`, which restarts both.

## 2. Workspace PAT

1. Open the existing token first and note its owner, repository access and
   permissions. The replacement must match; a fine-grained token scoped to just
   the workspace repo is better than a classic one. **Verify** what the
   workspace actually needs (clone and push, or clone only) before narrowing.
2. Create the new fine-grained PAT with the shortest expiry you'll actually
   keep up with.
3. Put it in `github_pat` on `OpenClaw Workspace` in 1Password.
4. `just openclaw-quiet`, then `just deploy-openclaw`.
5. Check Brent can still read (and write, if that was allowed) the workspace:
   ask him to touch it, or look at the container logs for a git auth error.
6. Delete the old token.

## 3. Pickleclaw deploy key

The workspace deploy key is gone: it only did a one-time clone, and sync uses the PAT
(retired 2026-11-18, see the [openclaw README](../../homelab/services/openclaw/README.md#workspace-clone)).
That leaves the read-only pickleclaw key. 1Password generates the pair, so the private
half never touches disk.

1. `scripts/deploy-key-b64 new "Pickleclaw Deploy Key <yyyy-mm>"` makes an SSH Key item
   in the `picklehome` vault and prints the public key. It refuses to reuse a title.
2. On `technicalpickles/pickleclaw`, Settings, Deploy keys, Add deploy key with that
   public key. Leave "Allow write access" unchecked.
3. `scripts/deploy-key-b64 copy "Pickleclaw Deploy Key <yyyy-mm>"` puts the one-line
   base64 of the private key on the clipboard (cleared after 60 seconds). Paste it into
   `deploy_key_b64` on `OpenClaw Pickleclaw Deploy Key` in the 1Password app. It must
   stay one line, because `deploy.sh` decodes it with `echo "$KEY_B64" | base64 -d`.
4. `just openclaw-quiet`, then `just deploy-openclaw`.
5. Check: the deploy's "Cloning/updating pickleclaw" step succeeds, and on the repo's
   deploy keys page the new key shows a recent "Last used". The old key's date stops
   moving. The container has no ssh client, so there is no `ssh -T` check from there.
6. Delete the old deploy key on GitHub.

Both subcommands need the sandbox off and you at the laptop to approve 1Password.

## Done when

- Old OAuth secret, PAT and the old pickleclaw deploy key are deleted on GitHub.
- Woodpecker login and a pipeline both work.
- `just deploy-openclaw` finished cleanly with the new key.
