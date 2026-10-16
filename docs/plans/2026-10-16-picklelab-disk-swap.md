# picklelab disk swap: 111GB SanDisk to 1TB PNY

> Ops runbook, not a code plan. Almost every stage is a root shell on
> picklelab in an interactive `ssh -t picklelab` session with Josh typing the
> sudo password. The only code change is `disk-monitor-mounts`. Stages are
> slugs, not numbers; cite the slug.

**Goal:** picklelab runs from the 1TB PNY in the internal bay, with Docker
churn on its own LVs and the old SanDisk repurposed as a second backup target.

**Approach:** Copy online with LVM (`pvmove`) while the PNY sits in the USB
enclosure, fix up boot, prove it boots from the new ESP, then do one physical
swap. Grow and split LVs only after the swap has soaked.

**Research:** [`docs/research/picklelab-disk-swap/findings.md`](../research/picklelab-disk-swap/findings.md)
(layout, fstab, open questions). Backlog: taskwarrior `639457b8` (swap),
`b584df49` (Docker LV split), `6885ef30` (build off-box, unaffected),
`b1c53be5` (disk_monitor latent bugs, same file as `disk-monitor-mounts`).

## Target layout

GPT on the PNY (no copy of `sda2`, it's an unused installer leftover):

| Part | Size | Type | Use |
|---|---|---|---|
| 1 | 1G | `ef00` | ESP, vfat, `/boot/efi` |
| 2 | 1G | `8300` | ext4, `/boot` |
| 3 | rest (~929G) | `8e00` | LVM PV in `vg0` |

`vg0` once everything's done:

| LV | Today | Target | Mount |
|---|---|---|---|
| root | 30G | 50G | `/` |
| srv | 70G | 100G | `/srv` |
| containerd | (dir on srv, 37G) | 150G | `/srv/containerd` |
| ci-docker | (dir on srv, 3.7G) | 30G | `/srv/ci-docker` |
| free | <9G | ~600G | snapshots, future LVs, online growth |

Why these sizes: growing an LV + ext4 is online and one command, shrinking
ext4 is offline (and needs a rescue boot for root). So allocate ~4-10x
current use and leave the rest free. `/srv/docker` (the main daemon's
`data-root`: volumes, container metadata, capped json-file logs) stays on
`srv` because it's closer to state than churn. New LVs mount at the existing
paths so `daemon.json`, containerd's `root`, and the rootless CI config don't
change.

## Global constraints

- **Refer to disks by `/dev/disk/by-id/`**, never `sdX`. The PNY is `sdb` now
  and becomes `sda` after the swap. In this doc `$NEW` is the
  `usb-PNY_1TB_SATA_SSD_*-0:0` link and `$OLD` is the `ata-SanDisk_SDSSDA120G_*`
  link. Don't paste the full by-id names (they contain serials) into anything
  committed.
- **Never have two filesystems with the same UUID attached.** So no `dd` of
  partitions: make new filesystems and update fstab and grub to match.
- **No LV grows or new LVs until `soak` passes.** Until then `vg0` fits on
  `sda4` (100G allocated, 109G PV), so a reverse `pvmove` back to the SanDisk
  is the rollback.
- Sudo is interactive (`ssh -t`). Don't widen `homelab/config/sudoers-deploy-ops`
  for this.

## Review focus

Ways this goes wrong that no step "tests" by default. Each one has a check in
its owning stage.

1. **Boot fixup is incomplete.** Ubuntu's ESP stub (`EFI/ubuntu/grub.cfg`)
   finds `/boot` by filesystem UUID. Copy the ESP without re-running
   `grub-install`, and the new ESP keeps pointing at the *old* `/boot`, which
   is gone after the swap: you get a grub rescue prompt. Check is in
   `boot-fixup`.
2. **The only backup lives on the disk being migrated.** restic's repo is
   `/srv/backups/restic`, same SSD. An off-box copy has to exist before
   `migrate-lvm`. Check is in `preflight`.
3. **disk_monitor goes blind after the split.** It hardcodes
   `FILESYSTEMS = ["/", "/srv"]` and uses `du -x /srv`, so the new LVs (the
   ones most likely to fill) would never alert. Ship `disk-monitor-mounts`
   before `docker-split`.
4. **Rootless CI daemon gets missed during the split.** It runs as user `ci`
   (uid 2000) under `user@2000.service`, separate from the system Docker.
   Stopping only `docker` leaves it writing to `/srv/ci-docker` mid-copy.
5. **BIOS boots the wrong ESP, or none, after the swap.** The NVRAM entry
   `grub-install` writes points at the PNY's ESP partition GUID, which moves
   with the disk. `EFI/BOOT/BOOTX64.EFI` (already present, gets copied) is
   the fallback. Both get proven in `test-boot` before anything physical
   happens.

Already checked and fine (2026-10-16): both drives report 512-byte logical
sectors over USB, so the GPT survives the move to native SATA; Secure Boot is
disabled; the initramfs includes `uas` and `usb-storage`, so root-on-USB-LVM
boots for `test-boot`.

---

## Stages

### `preflight`

No changes to the box, except a backup run.

- [ ] Run a fresh backup: `just backup-now`, then `just backup-snapshots`
      shows one from today.
- [ ] Copy the restic repo off-box (Mac or NAS). E.g. on picklelab
      `sudo tar -C /srv/backups -cf - restic | ssh <mac> 'cat > ~/picklelab-restic-2026-10-XX.tar'`,
      or pull it the other way. Done when the tarball exists off-box and its
      size roughly matches `/srv/backups` (3.7G today).
- [ ] Prune so less gets copied: `sudo /opt/homelab/homelab/services/disk-hygiene/docker-prune.sh`
      (the weekly timer's script; ~16G is reclaimable right now).
- [ ] Record current state for comparison: `sudo disk-report`,
      `sudo efibootmgr -v`, `docker ps --format '{{.Names}}' | sort` (save
      the container list, that's what `swap` checks against).
- [ ] Resolve `$NEW`/`$OLD` (`ls -l /dev/disk/by-id/`), and confirm `$NEW`
      is 931.5G and has no partitions (`lsblk $NEW`).

### `partition-new`

- [ ] `sudo sgdisk -n1:0:+1G -t1:ef00 -n2:0:+1G -t2:8300 -n3:0:0 -t3:8e00 $NEW`
- [ ] `sudo mkfs.vfat -F32 ${NEW}-part1`, `sudo mkfs.ext4 -L boot ${NEW}-part2`
- [ ] Verify: `lsblk -f $NEW` shows vfat / ext4 / no fs on part3.

### `migrate-lvm`

Online, no downtime. Runs for a while (~100G over USB 3); run it under
`tmux` or `screen` so a dropped ssh doesn't matter (pvmove resumes anyway).

- [ ] `sudo pvcreate ${NEW}-part3 && sudo vgextend vg0 ${NEW}-part3`
- [ ] `sudo pvmove -i 60 /dev/sda4 ${NEW}-part3` (`-i 60` prints progress
      every minute). If it gets interrupted, plain `sudo pvmove` resumes.
      `sudo pvmove --abort` backs out.
- [ ] Verify: `sudo pvs` shows `sda4` with PFree == PSize (fully empty).
- [ ] `sudo vgreduce vg0 /dev/sda4 && sudo pvremove /dev/sda4`. The
      `pvremove` matters: without it, the SanDisk carries a stale `vg0` label
      that collides with the real one when it goes back into the enclosure.
- [ ] No fstab change needed: `/` and `/srv` mount by `dm-uuid-LVM-*`, which
      `pvmove` doesn't change. Confirm with `findmnt / /srv`.

### `boot-fixup`

- [ ] Copy `/boot`: mount `${NEW}-part2` at `/mnt/newboot`,
      `sudo rsync -aHAXx /boot/ /mnt/newboot/`. The `-x` keeps rsync from
      descending into the `/boot/efi` mount, so the copy gets an empty `efi`
      dir to mount the new ESP on.
- [ ] Copy the ESP: mount `${NEW}-part1` at `/mnt/newefi`,
      `sudo rsync -rt /boot/efi/ /mnt/newefi/`.
- [ ] Switch the live mounts: unmount `/mnt/*`, `umount /boot/efi /boot`,
      edit `/etc/fstab` to the new UUIDs (`blkid ${NEW}-part1 ${NEW}-part2`),
      `sudo mount -a`, then `findmnt /boot /boot/efi` shows the PNY's
      partitions. Keep a copy of the old fstab as `/etc/fstab.pre-swap`.
- [ ] `sudo grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=ubuntu`
      and `sudo update-grub`.
- [ ] **Review focus #1 check:** `grep -i uuid /boot/efi/EFI/ubuntu/grub.cfg`
      shows the *new* `/boot` UUID, not `238a1829-...`.
- [ ] `sudo efibootmgr -v` shows an `ubuntu` entry whose partition GUID
      matches `${NEW}-part1` (`blkid -s PARTUUID`).

### `test-boot`

First downtime (one reboot, a few minutes). Proves the PNY boots on its own
while the SanDisk is still internal and untouched as an ESP.

- [ ] `sudo efibootmgr -n <new entry num>` (BootNext, one-shot) and reboot.
- [ ] After reboot: `findmnt /boot/efi` is the PNY's part1 and
      `cat /proc/cmdline` looks normal; containers come back (compare to the
      `preflight` list).
- [ ] If the BIOS ignores BootNext for a USB device, that's fine as a
      finding, not a failure: note it and rely on the fallback path after the
      swap. If it *tries* and fails to boot, stop and debug here, with the
      SanDisk still bootable.

### `swap`

The real downtime: shut down, move drives, boot. Expect ~15-20 minutes
including ~20 containers coming back.

- [ ] Final `docker ps` list, then `sudo shutdown -h now`.
- [ ] Pull the PNY out of the Ugreen case, SanDisk out of the NUC bay, PNY
      into the bay. SanDisk goes in the Ugreen case but **stays unplugged**
      for now.
- [ ] Power on. If it doesn't find a boot entry, pick the PNY from the BIOS
      boot menu (F10 on the NUC6), which uses `EFI/BOOT/BOOTX64.EFI`.
- [ ] Verify: `lsblk` shows the PNY as `sda` with all mounts, `docker ps`
      matches the `preflight` list, `just disk-monitor-check` is quiet,
      Tailscale Services resolve.

### `soak`

- [ ] Leave it a few days. At least one nightly restic backup and one weekly
      prune run succeed. After this, the reverse-`pvmove` rollback is
      deliberately given up.

### `disk-monitor-mounts`

Code change, its own PR. Can land any time before `docker-split`.

**Files:** `homelab/services/disk_monitor/disk_monitor.py`,
`homelab/services/disk-hygiene/disk-report.sh`,
`tests/homelab/test_disk_monitor.py`, `homelab/services/disk_monitor/README.md`.

- [ ] Test first: `parse_df` handles four mounts, and `should_alert` fires
      for `/srv/containerd` at 90% while `/` and `/srv` are fine.
- [ ] `FILESYSTEMS = ["/", "/srv", "/srv/containerd", "/srv/ci-docker"]`,
      and `get_disk_usage` builds its `df -k` from `FILESYSTEMS` instead of
      the hardcoded `/ /srv`. A mount that doesn't exist yet must not break
      the run (`df` errors on it; tolerate partial output).
- [ ] Drop `-x` from `du -xh -d1 /srv` in both `get_top_paths` and
      `disk-report.sh` (so the top-paths list still shows containerd/ci-docker
      once they're separate mounts), and add `df -h` for the new mounts to
      `disk-report.sh`.
- [ ] While in the file, consider folding in `b1c53be5`'s items (hardcoded
      `PICKLELAB_USER = "kenny"`, exit 0 on ssh failure), or leave them for
      that task.
- [ ] `uv run pytest tests/homelab/test_disk_monitor.py`, deploy
      `disk-hygiene` (for `disk-report.sh`), README says which mounts are
      watched.

### `docker-split`

Second, short downtime for Docker only (the host stays up). Taskwarrior
`b584df49`; update its description, its "~19G VFree" figure is stale.

Why after the swap and not folded into it: creating LVs on the PNY breaks the
reverse-`pvmove` rollback, and the split's own downtime is minutes with a
pre-seeded rsync. A second short window beats losing the escape hatch during
the riskiest part.

- [ ] `sudo lvcreate -L 150G -n containerd vg0 && sudo mkfs.ext4 /dev/vg0/containerd`;
      same with `-L 30G -n ci-docker`.
- [ ] Pre-seed while running: mount each at `/mnt/<name>`,
      `sudo rsync -aHAX --numeric-ids /srv/containerd/ /mnt/containerd/`
      (and ci-docker). Inconsistent copy, the final pass fixes it.
- [ ] Stop everything that writes there (**review focus #4**): the systemd
      service units for the compose stacks, `sudo systemctl stop docker docker.socket containerd`,
      and the rootless one: `sudo systemctl stop user@2000.service`. Verify
      `pgrep -a containerd` and `pgrep -u ci dockerd` are empty.
- [ ] Final pass: same rsync with `--delete`.
- [ ] Unmount `/mnt/*`, `mv /srv/containerd /srv/containerd.old` (same for
      ci-docker), `mkdir` the empty mountpoints, add fstab lines by
      `/dev/disk/by-id/dm-uuid-LVM-*` (match the existing style: `ls -l
      /dev/disk/by-id/ | grep dm-uuid`), `sudo mount -a`. Check the mounted
      dirs' owner/mode match the `.old` ones (`stat`), especially
      `/srv/ci-docker` owned by `ci`.
- [ ] Start things back up (`user@2000.service`, docker, the service units),
      compare `docker ps` to the `preflight` list, and run a CI build to prove
      the rootless daemon works.
- [ ] After a day of normal running: `sudo rm -rf /srv/containerd.old /srv/ci-docker.old`.

### `grow`

Online, no downtime.

- [ ] `sudo lvextend -r -L 50G vg0/root` and `sudo lvextend -r -L 100G vg0/srv`
      (`-r` resizes the ext4 too).
- [ ] `sudo vgs` shows ~600G free; `disk-report` looks like the target layout table.

### `second-backup-target`

The old SanDisk becomes a second local restic repo (`639457b8`'s last part).
Small enough to fold in here, but its details belong to the backup service,
so it gets its own PR touching `homelab/services/backup/`.

- [ ] Plug the Ugreen case in. `lsblk` shows the SanDisk with its old
      partitions and no LVM label (the `pvremove` in `migrate-lvm`).
- [ ] `sudo wipefs -a $OLD`, single GPT partition, ext4, `nofail` fstab
      mount by UUID (mountpoint up to the backup PR).
- [ ] Second repo + schedule per `homelab/services/backup/README.md`; that
      PR owns the details.

## Close-out

- [ ] Update `findings.md` open questions, `homelab/docs/homelab_03_host_setup.md`
      (disk layout), and the README's homelab line if it mentions disk size.
- [ ] Close `639457b8` and `b584df49`; capture any followups in taskwarrior.
