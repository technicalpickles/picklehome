# Rotate Open WebUI, Open Terminal and UniFi credentials

Task `66790ff9`. See the [shared procedure](README.md#rotating-secrets) first.

| Secret | 1Password | Used by | Action |
|---|---|---|---|
| `OPEN_WEBUI_ADMIN_PASSWORD` | `picklehome/Open WebUI/admin_password` | the admin account in Open WebUI's database | Change in the UI, then store it |
| `OPEN_WEBUI_SECRET_KEY` | `picklehome/Open WebUI/secret_key` | session signing, read at startup | New value, redeploy. Signs everyone out |
| `OPEN_TERMINAL_API_KEY` | `picklehome/Open Terminal/api_key` | Open Terminal, and Open WebUI's connection to it | New value, redeploy, update the connection |
| `UNIFI_ADMIN_PASSWORD` | `picklehome/UniFi/credential` | UniFi controller login (`just unifi`) | Change on the controller |
| `UNIFI_API_KEY` | `picklehome/UniFi/api_key` | local UniFi API (`just unifi`) | Create a new key, delete the old |

## Open WebUI

The admin email and password env vars only act on a fresh, user-less database.
After first boot, changing the env value does nothing. The real password lives
in the database, so change it there and mirror it into 1Password
(`homelab/services/open-webui/README.md` explains the first-boot rule).

1. Open WebUI, Settings, Account, change the password. Use a generated one from
   1Password.
2. Put the same value in `admin_password`, so the two agree for any later fresh
   install.
3. Generate a new secret key with `openssl rand -hex 32`, put it in `secret_key`.
4. Generate a new terminal key the same way, put it in `api_key` on
   `Open Terminal`.
5. `just deploy-open-webui`
6. Everyone is signed out by the new secret key. Sign back in with the new
   password. **Verify** nothing else is encrypted with the secret key (stored
   connection secrets, for example); if chats or connections break, that is why.
7. Open WebUI, Admin Settings, Connections: update the Open Terminal connection
   to the new key. **Verify** where Open WebUI keeps it; it may live in the
   database like the Ollama key does.
8. Check: sign in, run a chat, run a terminal command from the UI.

## UniFi

Local consumers are the `network/unifi/` tools, run from the Mac with the `.env`
that `just dotenv` builds. Nothing on picklelab reads these.

1. UniFi controller, create a new API key (Integrations or Control Plane API,
   whichever your version names it). Store it in `api_key`.
2. Change the admin password in the controller's user settings. Store it in
   `credential`. If the controller is also signed into UniFi cloud, the cloud
   account password is a separate thing; note it if it's the same one.
3. `just dotenv`, then `just unifi clients` to prove both work.
4. Delete the old API key in the controller.

## Done when

- Open WebUI signs in with the new password and a chat plus the terminal work.
- `just unifi clients` works on the new credentials and the old key is deleted.
- `task 66790ff9 done`.
