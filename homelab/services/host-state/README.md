# host-state

Every 5 minutes picklelab writes one JSON report of what is broken on it. brined-almanac reads the report and files a taskwarrior task when a check stays bad.

## What it watches

`discover` rebuilds the set of checks on every run, so a new service is watched with no edit here.

| Check | Made for | Passes when |
|-------|----------|-------------|
| `timer-<stem>` | each `*.timer` in `/etc/systemd/system` that is a symlink into `/opt/homelab/` | the timer is active with a next run (a monotonic-only timer counts), its service's last result is `success`, and the service is not stuck activating for 3600s or more |
| `unit-<stem>` | each `*.service` there with the same symlink rule, minus instances (`name@.service`) and services a timer already claims | the unit is `active`. Not found is unknown, anything else critical |
| `site-<name>` | each line of `sites.conf` | `curl -L` gets a 2xx within 10s |

Units that are not symlinks into `/opt/homelab/` (distro units, anything hand-made) are not watched. A name outside `[a-z0-9-]` is skipped with one line on stderr and the run carries on.

`sites.conf` is one `<name> <url>` per line. Blank lines and `#` lines are ignored. The final status after redirects decides.

## The report

`/var/lib/host-state/picklelab.json`, mode 0644, written atomically. `checks/` beside it holds one small wrapper per check, rewritten by `discover`. `picklelab.conf` is the collector config, and `HOST_STATE_OUT` and `HOST_STATE_CHECK_DIR` override the two paths (the tests use them).

Read it:

```bash
ssh picklelab cat /var/lib/host-state/picklelab.json | jq
```

Each check has a `status` (0 OK, 2 critical, 3 unknown; the collector also accepts 1 for warning), a `since` time, and one line of `output`.

## Running it

Run the whole thing now and see its journal:

```bash
just host-state-run-now
```

Run one check by hand on picklelab:

```bash
sudo /var/lib/host-state/checks/timer-docker-prune
/opt/homelab/homelab/services/host-state/site-check https://bugsink.tail2023b7.ts.net/
```

Read the journal: `journalctl -u host-state.service -n 60 --no-pager`.

## Deploy

`just deploy-host-state` links the units, enables the timer, and runs the service once so a report exists straight away.

## Reaching the report from the Mac

The almanac pulls the file over SSH with a key fenced to one command. The `authorized_keys` line on picklelab is a hand edit, not part of this deploy. The line, the 1Password item, and the steps are in brined-almanac's `docs/runbooks/prod-on-the-mac.md`, section "Host state".

## `collect` is a copy

`collect` is brined-almanac's `checks/collect`, byte for byte, plus the header comment naming the source commit. Never edit it here. To refresh:

1. Copy `checks/collect` from brined-almanac at origin/main over `collect`.
2. Re-insert the header after the shebang with the new commit hash.
3. Copy the same file to `tests/homelab/fixtures/host_state/collect.upstream` and put the hash in `collect.upstream.commit`.
4. Run `uv run pytest tests/homelab -q`. `test_collect_is_a_copy` fails if the copy and the fixture differ.
