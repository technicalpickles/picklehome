# Rotate device and cloud account credentials

Task `e14a8367`. See the [shared procedure](README.md#rotating-secrets) first.

These are third-party accounts, so each rotation happens in that vendor's app or
console and the steps differ. This page gives the 1Password location, who reads
it and the kind of change. The vendor console layout is yours to confirm; mark
it here once you have.

Two consumers matter:

- **picklelab** reads only what `homelab/services/climate-auto-switch/.env.vars`
  lists: Ecobee, BlueAir, Google Pollen. Changing these needs
  `just deploy-climate`.
- **Everything else** is read by Mac-side tools through `just dotenv`. Updating
  1Password and re-running `just dotenv` is enough.

| Account | 1Password item (`picklehome`) | Kind | Read by |
|---|---|---|---|
| Ecobee | `Ecobee / api_key` | API key for the Ecobee developer app | picklelab and Mac |
| BlueAir | `BlueAir / username, password` | account login | picklelab and Mac |
| Google Pollen / Air Quality | `Google Air Quality API / api_key` | Google API key | picklelab and Mac |
| Google Places | `OpenClaw / google_places_api_key` | Google API key | openclaw's `goplaces-node` |
| Nest | `picklehome nest / client_id, client_secret` | Google OAuth client | Mac |
| Philips Hue | `Philips Hue / api_key` | bridge app key | Mac |
| LG ThinQ | `LG ThinQ / credential` | personal access token | Mac |
| Yale Access | `Yale Access / username, credential` | account login | Mac |
| Aladdin Connect | `Aladdin Connect / email, password` | account login | Mac |
| ConnectLife (Hisense) | `ConnectLife / username, password` | account login | Mac |
| Moen Flo | `Moen Flo / username, password` | account login | Mac |
| VicoHome | held by the feeder-journal repo | account login | feeder-journal |
| Cloudflare Radar | `Cloudflare Radar / credential` | API token | Mac |

## General method

1. Change the secret at the vendor (new password, regenerate key, new token).
   For a password, use a generated one from 1Password.
2. Update the 1Password field in the app.
3. For the three picklelab accounts: `just deploy-climate`.
4. `just dotenv`, then run the module's status command, listed in the README's
   integration table (`just blueair status`, `just locks status`, and so on).
5. Revoke the old key or token last.

## Notes per account

- **Ecobee.** The API key is for the developer app, and the working tokens are
  separate OAuth tokens cached in `climate-auto-switch`'s data directory
  (`~/.local/state/picklehome/ecobee-tokens.json` on the Mac). **Verify** whether
  changing the key invalidates the tokens; if it does you re-run the PIN flow
  (`just climate-*` auth) on the Mac and copy fresh tokens to picklelab.
- **BlueAir, Yale, Aladdin, ConnectLife, Moen Flo.** Plain logins. Changing the
  password at the vendor signs out other sessions, so cached session tokens in
  `~/.local/state/picklehome/<service>-tokens.json` become invalid and get
  re-fetched on next use. Delete the token file if a module doesn't recover.
  Check Yale last: the lock bridges rely on the same account.
- **Aladdin.** The Cognito client id and secret in the module are constants from
  the app, not yours. Only the login rotates.
- **Nest.** Rotate the OAuth client secret in Google Cloud Console (the project
  behind Device Access). The stored refresh token belongs to the old client
  secret, so run the loopback browser sign-in again and let it write a new
  `nest-tokens.json`. **Verify** whether the token file also needs recreating.
- **Hue.** The app key is created by pressing the bridge button and calling the
  bridge. Make a new one, test, then delete the old key through the bridge API
  (`DELETE /api/<key>/config/whitelist/<old>`). Needs the Mac on the same LAN.
- **LG ThinQ.** The personal access token is created in the LG developer portal.
  Create a new one, test `just lg status`, then delete the old.
- **Google keys (Places, Pollen).** In Google Cloud Console, create a new key
  with the same API restriction, update 1Password, deploy, check, then delete
  the old. Places is read by openclaw, so that one needs `just openclaw-quiet`
  then `just deploy-openclaw`; fold it into the
  [OpenClaw](rotate-openclaw.md) deploy.
- **Cloudflare Radar.** Create the new API token with the same scope, then roll
  or delete the old.
- **VicoHome.** The unofficial API logs in with user and password; change the
  password in the app and update the feeder-journal repo's own secret.

## Order

Cheapest first, so progress shows early: Cloudflare Radar, Google keys, LG, Hue.
Then logins (BlueAir, ConnectLife, Moen Flo, Aladdin, Yale, VicoHome). Then
Ecobee and Nest, which are the ones that can need a re-auth flow.

## Done when

- Each module's status command works on the new credential.
- `just deploy-climate` has run, and the next 15-minute climate timer succeeds.
- Old keys and tokens are revoked.
- `task e14a8367 done`.
