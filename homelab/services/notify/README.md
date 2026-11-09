# notify

Telegram alerts for picklelab. Pipe text into one command and it reaches Josh's phone.

```
some-check | /opt/homelab/homelab/scripts/notify-telegram.sh
```

Callers never see a token, an env file, or the Telegram API.

## Pieces

| Piece | Owns |
|---|---|
| `homelab/scripts/notify_telegram.py` | stdin to Telegram: plain text, truncation, exit codes, token redaction |
| `homelab/scripts/notify-telegram.sh` | Loads the op service-account token and runs the notifier under `op run` with this service's filtered template. Needs root |
| `.env.vars` | The alert env vars: `TELEGRAM_ALERT_BOT_TOKEN`, `TELEGRAM_ALERT_CHAT_ID` |
| `notify-failure@.service` | Template unit. Sends the last 25 journal lines of the unit named by its instance |
| `deploy.sh` | Writes the filtered template and links the template unit |

The bot token and chat id live in the `picklehome` vault, item `Picklelab Alerts Telegram` (fields `credential` and `chat_id`).
`TELEGRAM_ALERT_THREAD_ID` is optional and not wired through 1Password. Set it in the environment to post into a forum topic.

## Deploy

```
just deploy-notify
```

Run this before `just deploy-disk-monitor`. The monitor's wrapper reads the template this writes.

## Alert when a unit fails

Add one line to the unit's `[Unit]` section:

```
OnFailure=notify-failure@%n.service
```

`backup.service` does this. If Telegram is down, `notify-failure@` fails and logs. It does not retry and does not alert about itself.

## Try it

```
echo test | sudo /opt/homelab/homelab/scripts/notify-telegram.sh
```
