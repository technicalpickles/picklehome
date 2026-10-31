# Moving local secrets to Automic Vault (pilot)

Local dev secrets come from `.env`, which `just dotenv` builds from 1Password. This pilot moves a small slice of them (the Moen Flo and Skylight logins) into Automic Vault (`av`) and reads them through [varlock](https://varlock.dev). Everything else stays on `just dotenv`, and the homelab hosts stay on 1Password (`op run` in the systemd units, `.env.template` filtered by `service-env`). This doesn't touch the deploy side.

## Pieces

- `.env.schema` lists the keys varlock resolves. `FLO_USERNAME`, `FLO_PASSWORD`, `SKYLIGHT_EMAIL` and `SKYLIGHT_PASSWORD` come from `av()`, `FLO_USE_SSO` is a plain default.
- `.mise.toml` adds node 24 and `npm:varlock` 1.24.0. The standalone varlock binary is rejected by Automic Vault, so it has to run under node.
- `scripts/load-secrets` copies values from 1Password into `av`. It reads each reference from `.env.template`, so references still live in one place.
- `just water-av` runs the Flo CLI under varlock. `just water` is unchanged.

## Setup

```sh
mise install
mise run setup          # once: confirm and cache the pinned Automic Vault plugin
mise run load-secrets   # 1Password and Automic Vault each ask to approve
just water-av status
```

`mise run load-secrets -- FLO_PASSWORD` loads just the named keys. Skylight has no entry in `.env.template` yet, so its map entries in `scripts/load-secrets` are TODO and the script skips them (or refuses, if you name one).

## Gotchas

- **`.env` shadows the vault.** Precedence, low to high, is schema, `.env`, `.env.local`, then the caller's environment. A `FLO_*` or `SKYLIGHT_*` line left in `.env` wins over `av()`, so after `load-secrets` delete those lines from `.env`. `just dotenv` writes them back, so until the template drops them this is a manual step after every run.
- **`set dotenv-load` stays.** `just` still loads `.env` for every recipe, which is why the other integrations keep working. It never sees the vault values; `varlock run` hands them to the child process.
- **Every `av()` is requested on every run**, and a Secret that isn't saved fails the whole load. That's why the schema is tiny and why `water-av` fails until `load-secrets` has run.
- **Approvals.** Expect about one prompt per wrapped `just` run, and two per key when loading (one from 1Password, one from Automic Vault).
- `@disableProcessEnvInjection` is required by the plugin. `varlock run` still gives the child the values.
