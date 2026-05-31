# Climate Automation — Setup Guide

A first-time, step-by-step walkthrough for the Ecobee climate tools (schedule sync, comfort
setpoints, status). For command reference and architecture, see
[`climate/README.md`](../climate/README.md). For secrets handling generally, see the project
[`CLAUDE.md`](../CLAUDE.md).

---

## Prerequisites

Install these before starting:

- **[just](https://github.com/casey/just#installation)**: task runner (`brew install just`)
- **[mise](https://mise.jdx.dev/getting-started.html)**: toolchain manager, pins Python/uv/go (`brew install mise`)
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)**: Python package manager (`brew install uv`)

`.mise.toml` pins the Python and uv versions for the repo. After installing mise, trust the
config so it activates:

```bash
mise trust
```

You also need the [1Password CLI](https://developer.1password.com/docs/cli/) (`op`) signed in,
since secrets are injected from 1Password (`op signin`).

---

## Step 1: Install Python dependencies

Run once after cloning the repo:

```bash
just install   # uv sync: creates .venv/ with all dependencies
```

---

## Step 2: Register an Ecobee developer app

1. Go to [ecobee.com/developers](https://www.ecobee.com/en-us/developers/) and sign in
2. Click **Create New Application**
3. Give it a name (e.g. `picklehome`)
4. Set **Authorization Method** to **ecobee PIN**
5. Click **Create** and copy the **API Key**

---

## Step 3: Store the API key in 1Password and generate `.env`

The API key lives in 1Password (`picklehome` vault, `Ecobee` item, `api_key` field), not in
the macOS Keychain. Store it, then inject it into `.env`:

```bash
op item edit Ecobee --vault=picklehome api_key=YOUR_KEY_HERE
just dotenv    # injects op:// references into .env (sets ECOBEE_API_KEY)
```

`just dotenv` reads `.env.template` and writes `.env`. The code loads `ECOBEE_API_KEY` from
`.env` at import time via `python-dotenv`. If the key is missing you'll see
`ECOBEE_API_KEY not set. Run 'just dotenv' to generate .env.`

---

## Step 4: Authorize with the PIN flow

```bash
just climate-auth
```

This prints a PIN and waits while you authorize it:

```
Authorization required!
  PIN: abcd-1234
  ...
Waiting for authorization (Ctrl-C to cancel)...
```

Enter the PIN at [ecobee.com](https://www.ecobee.com) under **My Apps → Add Application**
(about 9 minutes before it expires). Once authorized, the script detects it, lists your
thermostats, and saves tokens:

```
Thermostats on this account (add these to schedule.yaml):

  Living Room
    thermostat_id: "123456789012"
    Available climates: home, away, sleep, smart1, smart2

Setup complete! Tokens saved to ~/.local/state/picklehome/ecobee-tokens.json
```

Tokens are stored at `~/.local/state/picklehome/ecobee-tokens.json` (0600) and refreshed in
place automatically on later use.

---

## Step 5: Register thermostats and edit the schedule

Two config files in `climate/config/`:

1. **`thermostats.yaml`** — registry mapping each thermostat name to the `thermostat_id` from
   step 4 output.
2. **`schedule.yaml`** — the weekly program, referencing thermostats by name and time slots by
   their `climateRef` (e.g. `home`, `away`, `sleep`).

Schedule rules:
- All 7 days required: `sunday` through `saturday`
- Each day must start with `time: "00:00"`
- All times on 30-minute boundaries (`:00` or `:30`)
- YAML anchors (`&weekday` / `*weekday`) can share a schedule across days

> Read [`climate/spec/hvac-spec.md`](../climate/spec/hvac-spec.md) first. It's the source of
> truth for intended behavior; derive YAML changes from it rather than the other way around.

---

## Step 6: Preview the schedule

```bash
just climate-sync-dry
```

Prints the transitions it would push and ends with `Dry run complete. No changes pushed.`
Inspect it and confirm the transitions match your intent.

---

## Step 7: Push the schedule

```bash
just climate-sync         # prints "Schedule pushed successfully."
just climate-validate     # confirm the live Ecobee schedule matches schedule.yaml
```

Temperature and fan settings are left unchanged; only the weekly program is updated.

---

## Checking live status

```bash
just climate-status            # current state per thermostat
just climate-status --json     # machine-readable
```

```
Downstairs   70.4°F  58% humidity  idle        Comfort Cool  heat mode
Upstairs     70.1°F  62% humidity  idle        hold until 10:00am tomorrow
Outdoor      61.4°F  Rain · 13mph SW  (station NCQ)
```

---

## Troubleshooting

| Error message | Cause | Fix |
|---|---|---|
| `ECOBEE_API_KEY not set. Run 'just dotenv' to generate .env.` | Key missing from `.env` | Verify the `Ecobee` 1Password item has `api_key`, then `just dotenv` (check `op whoami`) |
| `Ecobee tokens not found. Run 'just climate-auth' to authorize.` | No token file yet | Run `just climate-auth` (step 4) |
| `Tokens invalid. Re-run 'just climate-auth'.` | Tokens revoked or expired beyond refresh | Re-run `just climate-auth` |
| `Thermostat 'X' in schedule.yaml not found in thermostats.yaml` | Name in `schedule.yaml` isn't registered | Add it to `thermostats.yaml` (step 5) |
| `Missing days in schedule: [...]. All 7 days are required.` | One or more day keys missing | Add the missing days to `schedule.yaml` |
| `Day 'X': first transition must be time '00:00'` | Day doesn't start at midnight | Add `time: "00:00"` as the first entry for that day |
| `Time X not 30-minute aligned.` | Time like `06:45` used | Change to a `:00` or `:30` boundary |
| `Unknown climate(s): [...]` | Climate ref not on the thermostat | Use a climate ref shown by `just climate-auth` |

**Full reset:** delete `~/.local/state/picklehome/ecobee-tokens.json`, then re-run from step 4.
