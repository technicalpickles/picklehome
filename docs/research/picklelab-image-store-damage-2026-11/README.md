# picklelab image store damage, 2026-11-14

Status: **cause not settled.** Everything below is evidence and a ranked list of
hypotheses, kept so the conclusion can be rederived rather than trusted. Raw
inputs are in `evidence/`; local reproductions are in `repro/`.

## Symptom

After the host rebooted 2026-11-14 20:13 UTC, openclaw, obsidian-sync and nikke
failed to start and brineworks-server crash-looped. Docker's containerd image
store referenced content and snapshots that are not on disk.

## What changed on the host, in order

| When (UTC) | Event | Source |
|---|---|---|
| 2026-11-10 14:28 to 14:30 | containerd stopped and started on the new `vg0-containerd` LV (disk split cutover) | `evidence/containerd-restarts.log`, `homelab/scripts/disk-swap/docker-split.sh` |
| 2026-11-11 to 11-13 | builds and deploys worked (no missing-content errors) | journal, 0 hits 11-10 14:30 to 11-14 06:40:57 |
| 2026-11-13 ~00:59 | `docker-split.sh cleanup` removed `/srv/containerd.old` | `disk-swap` log |
| 2026-11-14 04:04 to 04:05 | weekly `docker-prune.service` (Sat 04:04) ran `docker builder prune -f` and `docker image prune -f` on both roots | `evidence/prune-2026-11-14.log` |
| 2026-11-14 06:40:54 to :58 | glibc upgrade, systemd re-exec, needrestart restarted **containerd** (deferred docker). Within 1s, NotFound for all 17 containers in namespace `moby`. About 2,000 errors/hour afterwards | journal, `evidence/containerd-restarts.log` |
| 2026-11-14 20:13 | host reboot. Containers that survived metadata loss restart; 9 containers exist afterwards | |
| 2026-11-15 18:03 | inventory taken | `evidence/ctr-check.2026-11-15T18-03Z.out` |

## Measured facts

- **Damage is confined to 3 locally built images** of 28: `obsidian-sync:latest`
  (index blob missing), `brineworks-server:local` (6 of 18 blobs),
  `openclaw-goplaces-node:latest` (2 of 12 blobs). All 25 registry-pulled images
  are complete and unpacked. (`ctr -n moby images check`)
- **90 of 416** referenced blobs in `moby` have no file. **92 of 341** snapshots
  have no directory. (`ctr-check.sh` counts.)
- **The prune freed about 9G of files.** `/srv/containerd` was 37G before and 28G
  after the prune, in the same unit run (disk-report BEFORE and AFTER). Build
  cache went 232 records / 21.95G to 94 / 13G. `docker system df` showed 24
  images and 26.63GB both before and after.
- **`docker system df` reads metadata, not files.** It cannot see missing
  layers. This is why nothing looked wrong between the prune and the restart.
- **The rootless `ci` store is intact and acts as a control.** `ctr images check`
  reports no errors, snapshot metadata matches the directories on disk (119), and
  it holds 8 registry-pulled images. It went through the same disk-split cutover
  (same script, same day), the same weekly prune (build cache 255 records to 14,
  about 7G), and the same reboot. It has its own containerd, which needrestart did
  not restart at 06:40. It has no locally built images, so it cannot say whether
  the prune hurts local builds. (`evidence/ci-docker-check.2026-11-15T18-26Z.out`)
- `moby_history` is a normal namespace: the `ci` containerd has it too. It is not
  something a person created.
- Kernel log shows no ext4, I/O or dm errors since 11-10.
- containerd on the host is v2.2.2, docker 29.6.0.

## Hypotheses

| # | Hypothesis | Status | Why |
|---|---|---|---|
| H1 | Prune deleted files that images still reference | **open, leading** | Right size (9.0G reclaimable vs 9G drop), right day, and nothing re-reads layers until a restart, so quiet until 06:40 is expected. Not reproduced (see below). The 9G only proves the prune freed its own cache, not that it touched image layers. |
| H2 | containerd restart exposed damage that already existed | **supported** | Restart is when errors begin. Does not say who removed the files. |
| H3 | containerd restarted onto stale metadata (older than the data) | open, weaker | Registry images are all intact; stale metadata would be expected to hit them too. But all 17 container records vanished at restart, which looks like a metadata rollback. Unexplained. |
| H4 | disk split lost files (seed/cutover copy) | **unlikely** | Builds and containers worked 11-10 to 11-13, and containerd was restarted on the new LV at 14:30 on 11-10. The `ci` store went through the identical cutover and is intact. |
| H5 | `.old` cleanup removed live files | **ruled out** | containerd restarted after cutover, so nothing held `.old`. |
| H6 | missing mount | **ruled out** | `/srv/containerd` mounted from `vg0-containerd` throughout (disk-report). |
| H7 | filesystem or hardware errors | **ruled out** | no kernel errors. |

## Reproduction attempts

`repro/prune-vs-local-build.sh` and `repro/prune-cache-mounts.sh` run a throwaway
`docker:29.6.0-dind` with the containerd image store, build local images (shared
base layers, cache mounts, retagged rebuilds), run the same two prune commands as
`docker-prune.sh`, restart dockerd, and run `ctr images check`.

**Result: not reproduced** on docker 29.6.0 (containerd 2.2.4 in the dind image,
2.2.2 on the host) and on 29.9.3. The prune reclaimed cache-mount records (188MB)
and every image stayed complete after a restart. So the plain
prune-plus-restart sequence is not sufficient. What the repro does not cover:
scale (232 records), the disk-split history, buildx through compose, the rootless
`ci` daemon, the real image set.

## Not yet checked

- `moby_history` holds 7,550 blobs on the main store, far more than `moby`'s 416.
  The namespace is normal, but what fills it and whether it keeps the missing
  blobs alive are unchecked.
- Why all container records vanished at the 06:40 restart (H3). Needs the
  containerd bolt `meta.db` from before the restart, which was not kept.
- `nikke:local` reports complete and unpacked, so its failure is a different
  cause (likely its container snapshot).
- Whether the prune log's `Images 24 / 16 active` held through 11-07 and earlier
  Saturdays while images were later found fine (a baseline `images check` was
  never taken before this).

## Changes made because of this

- `docker-prune.timer` stopped on picklelab 2026-11-15 (manual `systemctl stop`).
- This PR: remove `docker builder prune` from the weekly prune until it is shown
  safe, and add an image integrity check (`ctr -n moby images check`) to the host
  checks, so damage is found the day it happens instead of at the next restart.
- Separately, needrestart no longer restarts containerd (pickleclaw-adjacent PR
  225 in picklehome).

## How to rederive

1. `evidence/ctr-check.sh` is read-only; run it as root on picklelab and diff
   against `evidence/ctr-check.2026-11-15T18-03Z.out`.
2. `journalctl -u docker-prune.service --since "2026-11-14 04:00" --until "2026-11-14 04:10"` for the prune numbers.
3. `journalctl -u containerd --since 2026-11-09 | grep -E "Stopping|Started"` for restart times.
4. Run the two scripts in `repro/` to confirm the plain prune does not break a clean dind store.

Tracked in taskwarrior (UUID prefixes): `854e3a62` (prune suspect), `9bc7abb8`
(rebuild), `764e6a93` (needrestart containerd).
