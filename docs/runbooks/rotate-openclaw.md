# Rotate OpenClaw tokens and model keys

Rotate these on a schedule, and whenever one leaks. See the [shared procedure](README.md#rotating-secrets) first.

All of these are read by the `openclaw` compose stack, so do them together and
deploy once.

| Secret | 1Password item and field | Vault | Notes |
|---|---|---|---|
| `OPENCLAW_GATEWAY_TOKEN` | `OpenClaw / gateway_token` | picklehome | Control UI and API bearer token |
| `TELEGRAM_BOT_TOKEN` | `Brent Pickleclawbot Telegram / credential` | Brent Pickleclaw | Same bot as the pickleclaw dev VM |
| `GOG_MCP_TOKEN` | `OpenClaw / gog_mcp_token` | picklehome | Checked by `gog-mcp`, sent by `openclaw` |
| `OLLAMA_API_KEY` | an item in `Brent Pickleclaw` | Brent Pickleclaw | Also read by Open WebUI |
| `OPENROUTER_API_KEY` | `OpenRouter API Key - pickleclaw macbook / credential` | Brent Pickleclaw | Embeddings only |
| `GEMINI_API_KEY` | `Brent Pickleclaw Gemini API Key / credential` | Brent Pickleclaw | `web_search`; shared with pickleclaw |

The three keys in the `Brent Pickleclaw` vault are shared with the pickleclaw
dev VM. Rotating them changes what that VM reads too, so tell whoever is using
it, and restart it after. The Telegram bot is one bot for both.

## Before you start

- `just openclaw-quiet` must pass, or wait. The deploy restarts Brent and kills
  an in-flight turn.
- Decide when to do the Telegram token. It takes effect the instant you revoke
  the old one, so Brent is offline from then until the deploy finishes. Do it
  last, with the new value already in 1Password and the deploy ready to run.

## Steps

1. **Gateway token.** Generate with `openssl rand -hex 32`, put it in
   `gateway_token`. Find anything else that holds the old one before you
   revoke it: a saved Control UI login in your browser, and anything under
   `homelab/` or the Open WebUI pipe that sends it. `git grep
   OPENCLAW_GATEWAY_TOKEN` lists the repo side. **Verify** there is no client
   outside the repo.
2. **GOG MCP token.** Generate the same way, put it in `gog_mcp_token`. The one
   env var feeds both the `openclaw` and `gog-mcp` services, so a single deploy
   keeps them in step.
3. **Model keys.** For each, create the new key in the provider's console
   (Ollama Cloud, OpenRouter, Google AI Studio), update the 1Password field,
   and leave the old key active until the check below passes. Restrict the
   Gemini key to the Generative Language API if it isn't already.
4. **Telegram token.** In Telegram, message BotFather: `/revoke`, pick the bot.
   BotFather replies with the new token immediately and the old one stops
   working. Put the new one in the 1Password field straight away.
5. `just deploy-openclaw`
6. Check, in this order:
   - the deploy's health wait passes;
   - send Brent a message on Telegram and get a reply (proves Telegram, Ollama
     and the allowlist);
   - ask him something that needs web search (Gemini) and something that needs
     memory recall (OpenRouter embeddings);
   - ask for something through the gog tools (GOG token). A 401 in the logs
     means the two services disagree on the token.
7. Revoke the old Ollama, OpenRouter and Gemini keys in their consoles.
8. Restart the pickleclaw dev VM so it picks up the new shared values.

## Open WebUI also holds the Ollama key

Open WebUI seeds connection settings from env on first boot only; after that its
database owns them. Updating 1Password and redeploying does not change the key
Open WebUI uses. Update it by hand: Open WebUI, Admin Settings, Connections
(see `homelab/services/open-webui/README.md`). **Verify** that this is the only
place; if Open WebUI also uses OpenRouter or Gemini, change those there too.

## Done when

- Brent answers on Telegram with search, memory and gog tools working.
- Open WebUI chats still reach Ollama.
- The old model keys are revoked and the Telegram token has been replaced.
