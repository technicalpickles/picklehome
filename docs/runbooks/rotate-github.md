# Rotate GitHub credentials

Task `d6ce7bad`. See the [shared procedure](README.md#rotating-secrets) first.

| Secret | 1Password | Used by | Action |
|---|---|---|---|
| `OPENCLAW_WORKSPACE_GITHUB_TOKEN` (PAT) | `picklehome/OpenClaw Workspace/github_pat` | openclaw, to reach the workspace repo | Replace the PAT, `just deploy-openclaw` |
| `WOODPECKER_GITHUB_CLIENT` / `_SECRET` | `picklehome/Woodpecker CI/github_client`, `github_secret` | Woodpecker's GitHub OAuth app login | New client secret, `just deploy-woodpecker` |
| `OPENCLAW_WORKSPACE_DEPLOY_KEY_B64` | `picklehome/OpenClaw Workspace/workspace_deploy_key_b64` | `deploy.sh`, one-time workspace clone | New key pair, `just deploy-openclaw` |
| `OPENCLAW_PICKLECLAW_DEPLOY_KEY_B64` | `picklehome/OpenClaw Pickleclaw Deploy Key/deploy_key_b64` | `deploy.sh`, clones `pickleclaw@main` (read-only) | New key pair, `just deploy-openclaw` |
| `WORKSPACE_DEPLOY_KEY_B64` | none now | brineworks-agent (torn down) | Delete the deploy key on GitHub |
| `GITHUB_RUNNER_TOKEN` | none now | self-hosted runner (retired, picklehome#151) | Confirm gone, nothing to rotate |

## 1. Dead credentials

- **Runner token.** It was a short-lived registration token and the runner is
  gone. Confirm GitHub, Settings, Actions, Runners shows no picklelab runner,
  and that no leftover `GITHUB_RUNNER_TOKEN` field remains in 1Password. Delete
  the field if there is one.
- **brineworks-agent deploy key.** On the repo it was attached to, Settings,
  Deploy keys, delete the key whose fingerprint matches the retired agent's
  `WORKSPACE_DEPLOY_KEY_B64`. If you can't tell which, the title and added date
  usually say. Nothing to deploy.

## 2. Woodpecker OAuth app

GitHub OAuth apps can hold two client secrets at once, so this has no downtime.

1. GitHub, Settings, Developer settings, OAuth Apps, the Woodpecker app,
   Generate a new client secret. Don't delete the old one yet.
2. Put it in `github_secret` on `Woodpecker CI` in 1Password. The client id does
   not change.
3. `just deploy-woodpecker`
4. Check: sign out of Woodpecker and sign back in with GitHub. Then push an
   empty commit to a repo with a pipeline and confirm it runs.
5. Delete the old client secret on the OAuth app.

`WOODPECKER_AGENT_SECRET` is a separate, internal shared secret. It wasn't in
the exposure list, so don't touch it here.

## 3. Workspace PAT

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

## 4. Deploy keys (workspace and pickleclaw)

Each is an ed25519 key pair. The private half goes into 1Password base64
encoded; the public half goes on the repo as a deploy key.

1. In a throwaway directory, generate the pair with no passphrase:
   `ssh-keygen -t ed25519 -N "" -C "picklelab-<purpose>" -f ./key`
2. Base64-encode the private key as a single line and paste it into the
   `*_deploy_key_b64` field in the 1Password app. **Verify** the encoding
   `deploy.sh` expects by reading how it decodes the field.
3. On the repo, Settings, Deploy keys, Add deploy key with `key.pub`. Match the
   old key's write-access setting: the pickleclaw key is read-only.
4. Delete the throwaway directory (`rm -P key key.pub` on macOS) once both
   halves are stored.
5. `just deploy-openclaw`
6. Check: the deploy's clone or pull step succeeds, or `ssh -T` with the new key
   from the container says it authenticated.
7. Remove the old deploy key from the repo.

## Done when

- Old OAuth secret, PAT and both old deploy keys are deleted on GitHub.
- Woodpecker login and a pipeline both work.
- `just deploy-openclaw` finished cleanly with the new keys.
- `task d6ce7bad done`.
