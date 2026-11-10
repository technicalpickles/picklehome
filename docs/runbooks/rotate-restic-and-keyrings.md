# Restic and keyring passwords

Task `16a96a24`. Read the [shared procedure](README.md#rotating-secrets), but
these three break it: a password that protects data at rest cannot be swapped by
editing 1Password, because the data was encrypted under the old one.

| Password | 1Password | Protects |
|---|---|---|
| `RESTIC_PASSWORD` | `picklehome/Restic Backup/password` | every backup in the restic repo |
| `BRINEWORKS_SERVER_KEYRING_PASSWORD` | `picklehome/Brineworks Server Keyring/password` | the stored Gmail tokens (a file keyring) |
| `GOG_KEYRING_PASSWORD` | `picklehome/OpenClaw/gog_keyring_password` | gog-mcp's stored OAuth refresh tokens (a file keyring) |

If you only edit the 1Password field and redeploy, the services can no longer
decrypt their own data. Each needs its own method. Decide first whether to rotate
at all (below).

## Decide: is rotating worth it?

The exposure was a transcript. A password that never left your machines is
useless to an attacker without also having the encrypted file or repo.

- **Restic.** The repo is a local directory on the NUC. To use the leaked
  password someone needs read access to `/srv/backups/restic`, which means they
  are already on the box. Rotating still removes a long-lived secret from a
  transcript, but the real risk is low until the repo moves off-box (a NAS or an
  S3 copy is planned). Do it before that happens, since afterwards a copy of the
  old password-protected repo exists elsewhere.
- **Keyrings.** Same argument: the encrypted files are on picklelab. The
  bigger win is rotating what's inside, the Gmail and Google OAuth tokens, by
  revoking them at Google and re-authorising. That makes the old password
  worthless even for a stolen file.

Pick one per password and write the decision on task `16a96a24`.

## Restic

Restic supports several keys per repo, which makes this safe: add the new key,
verify it, then remove the old one. The repo is not re-encrypted.

1. Back up first. Confirm the last snapshot is recent.
2. Generate the new password with `openssl rand -base64 32`. Keep it in the
   1Password app only. Losing it means losing every backup.
3. On picklelab, as the user that owns the repo, run `restic key add` against
   `/srv/backups/restic`. It prompts for the current password and the new one.
   Type them at the prompt; do not put them in the command.
4. Run `restic key list` and `restic snapshots` using the new password to prove
   it works.
5. Put the new password in `password` on `Restic Backup` in 1Password.
6. `just deploy-backup`, then start the backup service by hand and confirm it
   ran clean.
7. `restic key remove <old key id>`, then `restic key list` to confirm one key
   is left. Do not remove the key you are currently using.
8. Check `restic check` still passes.

**Verify** how the backup user reads `RESTIC_PASSWORD` on the host; the README
says `deploy.sh` resolves it through a root-owned wrapper rather than a file, so
the host copy updates with the deploy.

## Keyrings (Brineworks Gmail, gog)

A file keyring encrypts with a master password, and the password is only checked
when the file is opened. The routes, safest first:

1. **Re-authorise (preferred).** Revoke the app's access in the Google account
   security page, put the new password in 1Password, redeploy, then run the
   service's login flow again. It creates a new keyring under the new password
   and obtains new tokens, so the leaked password and the old tokens are both
   dead. Cost: one OAuth consent for each service.
2. **Re-key in place.** Only if the keyring library you use supports changing
   the master password. **Verify** this exists for the cryptfile backend before
   trying; do not experiment on the only copy. Copy the keyring file off first.

For either route:

- Stop the service so nothing is mid-write.
- Take a copy of the keyring file as a rollback.
- After redeploy, confirm a Gmail read (Brineworks) or a gog call works.
- Delete the rollback copy once the new one is confirmed.

Brineworks and gog redeploys need `just openclaw-quiet` first.

## Done when

- A decision is recorded on `16a96a24`, per password.
- For each one you rotated: the new password works, the old one no longer opens
  the data (restic: key removed; keyrings: re-authorised), and the next
  nightly backup succeeds.
- `task 16a96a24 done`.
