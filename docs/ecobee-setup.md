# Ecobee Schedule Sync — Setup Guide

This guide walks through first-time setup of the Ecobee schedule sync tool.

---

## Prerequisites

Install the following tools before starting:

- **[just](https://github.com/casey/just#installation)** — task runner (`brew install just`)
- **[mise](https://mise.jdx.dev/getting-started.html)** — Python version manager (`brew install mise`)
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** — Python package manager (`brew install uv`)

After installing mise, trust the project config:

```bash
mise trust
```

---

## Step 1: Install Python dependencies

Run once after cloning the repo:

```bash
just install
```

Expected output:

```
Resolved N packages...
Installed N packages...
```

This creates `.venv/` with all Python dependencies.

---

## Step 2: Register an Ecobee developer app

1. Go to [ecobee.com/developers](https://www.ecobee.com/en-us/developers/) and sign in
2. Click **Create New Application**
3. Give it a name (e.g., `picklehome`)
4. Set **Authorization Method** to **ecobee PIN**
5. Click **Create** and copy the **API Key**

---

## Step 3: Store your API key in macOS Keychain

Run `just install` first (step 1) so `keyring` is available, then:

```bash
uv run python -c "import keyring; keyring.set_password('picklehome-ecobee', 'api_key', 'YOUR_KEY_HERE')"
```

Replace `YOUR_KEY_HERE` with the API key from step 2.

**Expected:** macOS Keychain dialog appears requesting permission — click **Allow**.

You can verify the key was stored correctly by running `just climate-auth`; it will fail immediately with a clear message if the key is missing.

---

## Step 4: Authorize with PIN flow

```bash
just climate-auth
```

Expected output:

```
Authorization required!
  PIN: abcd-1234
  1. Go to https://www.ecobee.com → My Apps → Add Application
  2. Enter PIN above. You have approximately 9 minutes.

Waiting for authorization (Ctrl-C to cancel)...
....
Thermostat: Living Room (ID: 123456789012)
Available climates (use these in schedule.yaml):
  - home
  - away
  - sleep

Setup complete! Tokens and thermostat saved to Keychain.
```

Follow the PIN instructions in the terminal output. After authorizing in the Ecobee web UI, the script will detect it automatically.

**If you have multiple thermostats**, you will be prompted to select one by number.

---

## Step 5: Edit your schedule

Open `climate/config/schedule.yaml` and update the climate values using the `climateRef` strings shown in step 4 output (e.g., `home`, `away`, `sleep`).

Rules:
- All 7 days required: `sunday` through `saturday`
- Each day must start with `time: "00:00"`
- All times must be on 30-minute boundaries (`:00` or `:30`)
- YAML anchors (`&weekday` / `*weekday`) can be used to share a schedule across days

---

## Step 6: Preview the schedule

```bash
just climate-sync-dry
```

Expected output:

```
Schedule preview (transitions only):

Sunday
  00:00  Sleep
  08:00  Home
  23:00  Sleep
Monday
  00:00  Sleep
  06:30  Home
  08:30  Away
  17:00  Home
  22:00  Sleep
...
Dry run complete. No changes pushed.
```

Inspect the output and confirm the transitions match your intent. No changes are pushed.

---

## Step 7: Push the schedule

```bash
just climate-sync
```

Expected output:

```
Schedule pushed successfully.
```

Verify in the Ecobee app or web UI that your weekly schedule has been updated. Climate temperature and fan settings should be unchanged.

---

## Troubleshooting

| Error message | Cause | Fix |
|---|---|---|
| `Ecobee API key not found. See docs/ecobee-setup.md.` | API key not in Keychain | Re-run step 3 |
| `Ecobee tokens not found. Run 'just climate-auth' to authorize.` | Tokens missing from Keychain | Re-run `just climate-auth` |
| `Tokens invalid. Re-run 'just climate-auth'.` | Tokens revoked or expired beyond refresh | Re-run `just climate-auth` |
| `Thermostat ID not found. Run 'just climate-auth' first.` | `thermostat_id` not in Keychain | Re-run `just climate-auth` |
| `Error in schedule.yaml: Missing days in schedule: [...]` | One or more day keys missing | Add missing days to `climate/config/schedule.yaml` |
| `Error in schedule.yaml: Day 'X': first transition must be time '00:00'` | Day doesn't start at midnight | Add `time: "00:00"` as first entry for that day |
| `Error in schedule.yaml: Time X not 30-minute aligned` | Time like `06:45` used | Change to `:00` or `:30` boundary |
| `Error in schedule.yaml: Unknown climate(s): [...]` | Climate name not on thermostat | Use climate refs shown by `just climate-auth` |
| `Failed to fetch thermostat data from Ecobee.` | Network error | Check internet connection and retry |
| macOS Keychain dialog appears | First access to Keychain service | Click **Allow** |

**If you ever need to fully reset:** delete all entries under service `picklehome-ecobee` from Keychain Access, then re-run from step 3.
