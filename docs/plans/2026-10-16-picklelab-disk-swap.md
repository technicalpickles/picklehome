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
  link. After the swap the PNY's link changes to an `ata-PNY_*` one. Don't
  paste the full by-id names (they contain serials) into anything committed.
- **Never have two filesystems with the same UUID attached.** So no `dd` of
  partitions: make new filesystems and update fstab and grub to match.
- **No LV grows or new LVs until `soak` passes.** Until then `vg0` fits on
  the SanDisk (100G allocated, 109G PV), so a reverse `pvmove` is possible.
  See [Rollback](#rollback).
- **Automatic upgrades stay paused from `preflight` until `soak` ends.** A
  kernel or grub update landing mid-migration writes to whichever `/boot` and
  ESP happen to be mounted, and can leave the two disks disagreeing. Pause
  with `systemctl disable --now`, not `stop`: the timers are all `enabled`,
  so a plain `stop` is undone by the first reboot in `test-boot`.
- **`systemctl daemon-reload` after every fstab edit**, or systemd keeps
  stale mount units.
- Sudo is interactive (`ssh -t`). Don't widen `homelab/config/sudoers-deploy-ops`
  for this.

## Review focus

Ways this goes wrong that no step "tests" by default. Each one has a check in
its owning stage. A cold review (2026-10-16) added items 5-9.

1. **Boot fixup is incomplete.** Ubuntu's ESP stub (`EFI/ubuntu/grub.cfg`)
   finds `/boot` by filesystem UUID. Copy the ESP without re-running
   `grub-install`, and the new ESP keeps pointing at the *old* `/boot`, which
   is gone after the swap: you get a grub rescue prompt. Check is in
   `boot-fixup`.
2. **Backups cover less than the box.** restic backs up `/srv/data` only. Its
   repo lives on the disk being migrated, and once `pvmove` finishes the
   SanDisk is no longer a copy of anything (its extents are freed). `/etc`,
   `/var/lib/tailscale`, `/srv/docker/volumes`, and the `ci` user's config
   aren't backed up at all. `preflight` takes an off-box copy of all of it.
3. **disk_monitor goes blind after the split.** It hardcodes
   `FILESYSTEMS = ["/", "/srv"]` and uses `du -x /srv`, so the new LVs (the
   ones most likely to fill) would never alert. Ship `disk-monitor-mounts`
   before `docker-split`.
4. **Something writes during the Docker copy.** The rootless CI daemon runs
   under `user@2000.service`, separate from system Docker. And
   `docker-prune.sh` and `disk-report.sh` run `sudo -iu ci docker ...`,
   which opens a PAM session that respawns `user@2000` (linger is on). Stop
   the timers too, and re-check right before the final rsync.
5. **`grub-install` deletes the SanDisk's boot entry.** It removes every
   NVRAM entry with the same label (`ubuntu`) and puts the new one first. So
   without extra work there's no "SanDisk still bootable" fallback during
   `test-boot`. `boot-fixup` recreates it under another label.
6. **debconf still points grub at the SanDisk's ESP.** Confirmed:
   `grub-efi/install_devices` is the SanDisk's `scsi-0ATA_SanDisk_*-part1`.
   The next grub or shim upgrade would then fail its postinst (leaving dpkg
   half-configured) or install to the wrong disk. Re-pointed in `boot-fixup`
   and again in `swap`, since the PNY's by-id changes from `usb-*` to `ata-*`.
7. **The USB bridge resets under sustained I/O.** The PNY is on the `uas`
   driver (Realtek `0bda:9201`). From `migrate-lvm` to `swap`, root and
   `/srv` live on USB. A UAS reset there means I/O errors and ext4 going
   read-only, possibly mid-`pvmove`. `preflight` load-tests it, and the
   gap between `migrate-lvm` and `swap` should be the same day.
8. **A new LV doesn't mount at boot.** A plain fstab line that fails drops a
   headless box into emergency mode (no ssh). `nofail` is worse: Docker
   starts on the empty mountpoint dir and quietly refills `/srv`.
   `docker-split` uses `RequiresMountsFor=` plus an immutable empty
   mountpoint.
9. **The swap fails and there's no written way back.** See
   [Rollback](#rollback).
10. **The first reboot tests two things at once.** The box is running
    `6.8.0-146` but `6.8.0-147` was installed on 2026-10-14 and
    `/boot/initrd.img` already points at it. If `test-boot` is the first
    reboot, a failure could be the new kernel or the new disk.
    `rehearsal-reboot` boots 147 on the SanDisk first.
11. **A boot failure has no way in from the console.** GRUB is
    `GRUB_TIMEOUT_STYLE=hidden` / `GRUB_TIMEOUT=0` (no menu, no older kernel,
    no recovery entry), the firmware boot timeout is 1 second, and there's
    no drop-in on `emergency.service`. Ubuntu locks root by default, so a
    failed fstab mount ends at "root account is locked", not a shell.
    `rehearsal-reboot` opens all of these up for the migration window, and
    `soak` closes them again. See [When it won't boot](#when-it-wont-boot).

Already checked and fine (2026-10-16):
- Both drives report 512-byte logical sectors over USB, so the GPT survives
  the move to native SATA.
- Secure Boot is disabled.
- The initramfs includes `uas` and `usb-storage`, so root-on-USB-LVM boots
  for `test-boot`.
- The LVM devices file is off (`use_devicesfile=0`, no
  `/etc/lvm/devices/`), so a PV's by-id changing from `usb-*` to `ata-*`
  won't hide it from LVM.
- The initramfs also has `ahci`, `xhci-pci`, and `lvm`, so root is findable
  over SATA after the swap too.
- The kernel cmdline is `root=/dev/mapper/vg0-root ro`, with no `quiet`, so
  boot messages already reach the console.
- picklelab isn't DNS, DHCP, a subnet router, or an exit node. Downtime only
  takes out its own services.

Worth knowing (2026-10-16), not a problem:
- The firmware keeps its own entry at the front of BootOrder
  (`SATA : PORT 0 : SanDisk SDSSDA120G : PART 0 : Boot Drive`, a `BBS()`
  path, keyed on port and model). Boot still lands on the `Ubuntu` entry
  today. After the swap, expect the firmware to make a PNY version and maybe
  reorder things. That's one more reason the `EFI/BOOT/BOOTX64.EFI` fallback
  on the new ESP matters.
- BIOS is `0038` (2017). Don't update it as part of this: one variable at a
  time.

---

## Stages

### `rehearsal-reboot`

Two reboots on the SanDisk, before anything touches the PNY. It can be its
own day. It shakes out the new kernel (**review focus #10**), opens up the
console (**review focus #11**), and answers the BIOS questions while
nothing has changed. Needs a monitor and USB keyboard on the NUC. Downtime
is ~15 minutes.

- [ ] **Live USB.** The original install used `ubuntu-24.04.4-live-server-amd64.iso`
      on a Memorex 15GB stick (see `homelab/docs/homelab_03_host_setup.md`
      for writing one from the Mac). If the stick turns up, reuse it.
      Otherwise re-flash. 24.04.4 matches the running release. The server
      ISO has no desktop: get a shell from the installer's Help menu
      ("Enter shell") or Alt-F2. It ships `lvm`.
- [ ] **Open up the emergency shell.** `sudo systemctl edit emergency.service`
      and `rescue.service`, each with `[Service]` `Environment=SYSTEMD_SULOGIN_FORCE=1`.
      A failed mount now drops to a root shell on the console instead of
      "root account is locked". Anyone at the keyboard already has root via
      a live USB, so this gives nothing away. Also run `sudo passwd -S root`
      and note whether root is locked (`L`).
- [ ] **Make GRUB visible.** Write `/etc/default/grub.d/99-disk-swap.cfg`
      with `GRUB_TIMEOUT_STYLE=menu` and `GRUB_TIMEOUT=5`, then
      `sudo update-grub`. That gets you a menu with the older kernel and
      recovery mode (GRUB recovery mode is how the lost install password got
      reset, so that path has worked here before).
- [ ] **Longer firmware timeout:** `sudo efibootmgr -t 5`. The Intel firmware
      may ignore it; F10 at power-on works either way.
- [ ] Reboot 1, plain: `sudo reboot`. The GRUB menu shows for 5s, then
      `uname -r` is `6.8.0-147-generic` and `docker ps` comes back. A
      problem here is the kernel, not the disk: pick 146 from the menu, and
      fix it before going on.
- [ ] Optional, cheap: from the GRUB menu, `e`, add
      `systemd.unit=emergency.target` to the `linux` line, Ctrl-X. You
      should land in a root shell without a password prompt. `reboot`.
- [ ] Reboot 2, into the firmware: `sudo systemctl reboot --firmware-setup`.
      Photograph the boot settings (boot order, Fast Boot, UEFI/Legacy, USB
      boot) and change nothing. Exit, then with the live USB plugged in, hit
      **F10**. Note whether the menu offers the USB stick (this answers the
      `test-boot` fallback question). Boot it.
- [ ] In the live shell: `lvm vgchange -ay vg0`,
      `mount -o ro /dev/vg0/root /mnt`, `ls /mnt/etc`, then `umount /mnt`
      and `lvm vgchange -an vg0`. That proves the rescue path works on this
      hardware before you need it.
- [ ] Pull the stick and reboot. It comes back normally on the SanDisk.
- [ ] Record the BIOS findings in `findings.md` (USB in F10: yes/no,
      Fast Boot, Legacy/CSM).

### `preflight`

No real changes to the box: a backup run, a write test on the blank PNY, and
pausing the timers.

- [ ] Pause anything that writes on a schedule:
      `sudo systemctl disable --now apt-daily.timer apt-daily-upgrade.timer unattended-upgrades docker-prune.timer backup.timer`.
      `disable`, not `stop`, so they stay off through the reboots in
      `test-boot` and `swap`. They stay off until `soak` (backups run by
      hand with `just backup-now` in between). Check with
      `systemctl list-unit-files <same list>`: all `disabled`.
- [ ] Run a fresh backup: `just backup-now`, then `just backup-snapshots`
      shows one from today.
- [ ] Copy off-box (Mac or NAS) everything the box can't rebuild from the
      repo: `/srv/backups/restic`, `/etc`, `/var/lib/tailscale`,
      `/srv/docker/volumes`, `/home/ci/.config`. E.g.
      `sudo tar -cf - <paths> | ssh <mac> 'cat > ~/picklelab-pre-swap-2026-10-XX.tar'`.
      Done when the tarball exists off-box and `tar -tf` lists all five.
- [ ] Save metadata off-box too: `sudo vgcfgbackup -f /tmp/vg0.vgcfg vg0`,
      `sudo sgdisk --backup=/tmp/sandisk.gpt $OLD`, `sudo efibootmgr -v`,
      `sudo disk-report`, `cat /etc/fstab`, and the container list
      (`docker ps --format '{{.Names}}' | sort`, which is what later stages
      compare against).
- [ ] Prune so less gets copied: `sudo /opt/homelab/homelab/services/disk-hygiene/docker-prune.sh`
      (~16G is reclaimable right now).
- [ ] Resolve `$NEW`/`$OLD` (`ls -l /dev/disk/by-id/`), and confirm `$NEW`
      is 931.5G and has no partitions (`lsblk $NEW`).
- [ ] **SMART health on the PNY.** `smartctl` isn't installed:
      `sudo apt-get install smartmontools` (on the passwordless list). Then
      `sudo smartctl -d sat -H -A $NEW` (passed, zero reallocated/pending
      sectors) and `sudo smartctl -d sat -t short $NEW`, with the result in
      `-l selftest` a few minutes later. If the bridge won't pass SMART
      through, note it and rely on the load test.
- [ ] **Load-test the USB bridge (review focus #7)** while the PNY is still
      blank: `sudo dd if=/dev/zero of=$NEW bs=1M count=30000 oflag=direct status=progress`,
      then `sudo dmesg | grep -iE 'uas|reset|abort'`. Pass is no resets and a
      steady rate. If it resets, stop: either add the
      `usb-storage.quirks=0bda:9201:u` kernel arg (forces plain usb-storage,
      needs a reboot) and re-test, or switch to an offline clone.

### `partition-new`

- [ ] `sudo sgdisk -n1:0:+1G -t1:ef00 -n2:0:+1G -t2:8300 -n3:0:0 -t3:8e00 $NEW`,
      then `sudo udevadm settle` so the `-partN` links exist.
- [ ] `sudo mkfs.vfat -F32 ${NEW}-part1`, `sudo mkfs.ext4 -L boot ${NEW}-part2`
- [ ] Verify: `lsblk -f $NEW` shows vfat / ext4 / no fs on part3.
- [ ] Fill in the [When it won't boot](#when-it-wont-boot) cheat sheet with
      the new `/boot` UUID (`blkid -s UUID -o value ${NEW}-part2`) and keep
      it somewhere you can read it while the box is down (your phone, not
      picklelab).

### `migrate-lvm`

Online, no downtime. Runs for a while (~100G over USB 3). Run it under
`tmux` or `screen` so a dropped ssh doesn't matter.

- [ ] `sudo pvcreate ${NEW}-part3 && sudo vgextend vg0 ${NEW}-part3`
- [ ] Move one LV at a time so an abort only strands one of them:
      `sudo pvmove -i 60 -n root ${OLD}-part4 ${NEW}-part3`, then the same
      with `-n srv`. If it's interrupted, a bare `sudo pvmove` resumes.
      `sudo pvmove --abort` stops only the segment in flight. Anything already
      moved stays on the PNY, which is fine because it's all one VG either
      way.
- [ ] Verify: `sudo pvs` shows `${OLD}-part4` with PFree == PSize (fully
      empty).
- [ ] `sudo vgreduce vg0 ${OLD}-part4 && sudo pvremove ${OLD}-part4`. The
      `pvremove` matters: without it, the SanDisk carries a stale `vg0` label
      that collides with the real one when it goes back into the enclosure.
      This is the point where the SanDisk stops being a copy of anything.
- [ ] No fstab change needed: `/` and `/srv` mount by `dm-uuid-LVM-*`, which
      `pvmove` doesn't change. Confirm with `findmnt / /srv`.

### `boot-fixup`

Do the `/boot` copy and the mount switch back to back, so nothing can land
in between (upgrades are paused anyway).

- [ ] Copy `/boot`: mount `${NEW}-part2` at `/mnt/newboot`,
      `sudo rsync -aHAXx /boot/ /mnt/newboot/`. The `-x` keeps rsync from
      descending into the `/boot/efi` mount, so the copy gets an empty `efi`
      dir to mount the new ESP on.
- [ ] Copy the ESP: mount `${NEW}-part1` at `/mnt/newefi`,
      `sudo rsync -rt /boot/efi/ /mnt/newefi/`.
- [ ] Switch the live mounts: unmount `/mnt/*`, `umount /boot/efi /boot`,
      save `/etc/fstab.pre-swap`, edit `/etc/fstab` to the new UUIDs
      (`blkid ${NEW}-part1 ${NEW}-part2`), `sudo systemctl daemon-reload`,
      `sudo mount -a`, then `findmnt /boot /boot/efi` shows the PNY's
      partitions.
- [ ] `sudo grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=ubuntu`
      and `sudo update-grub`.
- [ ] **Review focus #1 check:** `grep -i uuid /boot/efi/EFI/ubuntu/grub.cfg`
      shows the *new* `/boot` UUID, not `238a1829-...`.
- [ ] **Review focus #5:** `grub-install` just deleted the SanDisk's `ubuntu`
      entry. Recreate it:
      `sudo efibootmgr -c -d $OLD -p 1 -L ubuntu-sandisk -l '\EFI\ubuntu\shimx64.efi'`.
      Then `sudo efibootmgr -o <sandisk>,<pny>,...` so the SanDisk is the
      default and the PNY is only tried when asked. The SanDisk's `/boot`
      (`sda3`) is frozen at copy time, which is fine as long as upgrades stay
      paused.
- [ ] **Review focus #6:** `sudo dpkg-reconfigure grub-efi-amd64-signed`
      (or `grub-efi-amd64`, whichever owns the question on this box), select
      only the PNY's ESP. Verify with
      `sudo debconf-show grub-efi-amd64 | grep install_devices`.
- [ ] Confirm the fallback path is on the new ESP: `/boot/efi/EFI/BOOT/`
      has `BOOTX64.EFI` and `fbx64.efi`, and `/boot/efi/EFI/ubuntu/BOOTX64.CSV`
      exists (`fbx64` uses it to rebuild a missing NVRAM entry).

### `test-boot`

Two reboots, a few minutes each. Proves the PNY boots on its
own while the SanDisk is still internal and is the default.

- [ ] NVRAM path: `sudo efibootmgr -n <pny entry>` (BootNext, one-shot) and
      reboot. After: `findmnt /boot/efi` is the PNY's part1, and containers
      come back (compare to the `preflight` list).
- [ ] Removable fallback path: reboot and pick the PNY's generic or USB
      entry from the F10 boot menu, which uses `EFI/BOOT/BOOTX64.EFI`.
      Same checks. If the BIOS won't offer USB here, note it. In that case the
      fallback only gets tested for real during `swap`.
- [ ] If either path *tries* and fails, reboot with nothing chosen: BootOrder
      lands on the SanDisk entry, and you debug from there.
- [ ] Once both pass: `sudo efibootmgr -o <pny>,<sandisk>,...` so the PNY is
      the default going into the swap.

### `swap`

The real downtime: shut down, move drives, boot. Expect ~15-20 minutes
including ~20 containers coming back. Same day as `migrate-lvm` if possible,
to keep root off USB for as little time as possible.

- [ ] Final `docker ps` list, then `sudo shutdown -h now`.
- [ ] Pull the PNY out of the Ugreen case, SanDisk out of the NUC bay, PNY
      into the bay. SanDisk goes in the Ugreen case but **stays unplugged**
      for now.
- [ ] Power on. If it doesn't find a boot entry, pick the PNY from the F10
      boot menu.
- [ ] Verify: `lsblk` shows the PNY as `sda` with all mounts, `docker ps`
      matches the `preflight` list, `just disk-monitor-check` is quiet,
      Tailscale Services resolve.
- [ ] Re-point debconf at the PNY's new `ata-*` ESP path
      (`dpkg-reconfigure` as in `boot-fixup`), and remove the dead
      `ubuntu-sandisk` NVRAM entry (`efibootmgr -b <num> -B`).

### `soak`

- [ ] Leave it a few days, with `just backup-now` run by hand nightly-ish
      while the timers are paused.
- [ ] Undo the console changes from `rehearsal-reboot`:
      `sudo systemctl revert emergency.service rescue.service`,
      `sudo rm /etc/default/grub.d/99-disk-swap.cfg && sudo update-grub`.
      Keep the 5s firmware timeout if you like it.
- [ ] Then re-enable everything paused in `preflight`
      (`sudo systemctl enable --now ...` for the same list), and watch one
      unattended-upgrades run, one nightly backup, and one weekly prune
      succeed. A grub or shim upgrade in this window is the real test of the
      debconf fix.
- [ ] After this, the reverse-`pvmove` rollback is deliberately given up.

### `disk-monitor-mounts`

Code change, its own PR (taskwarrior `9fd7f741`). Can land any time before
`docker-split`.

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
`b584df49`.

Why after the swap and not folded into it: creating LVs on the PNY breaks the
reverse-`pvmove` rollback, and the split's own downtime is minutes with a
pre-seeded rsync. A second short window beats losing the escape hatch during
the riskiest part.

- [ ] `sudo lvcreate -L 150G -n containerd vg0 && sudo mkfs.ext4 /dev/vg0/containerd`;
      same with `-L 30G -n ci-docker`.
- [ ] Pre-seed while running: mount each at `/mnt/<name>`,
      `sudo rsync -aHAX --numeric-ids /srv/containerd/ /mnt/containerd/`
      (and ci-docker). Inconsistent copy, the final pass fixes it. The
      trailing slashes mean rsync also copies the source dir's owner and mode
      onto the new filesystem's root.
- [ ] Stop everything that writes there (**review focus #4**):
      `sudo systemctl stop docker-prune.timer backup.timer` (if re-enabled
      after `soak`), the systemd units for the compose stacks,
      `sudo systemctl stop docker docker.socket containerd`, and
      `sudo systemctl stop user@2000.service`.
- [ ] Immediately before the final pass, check that `pgrep -a containerd`,
      `pgrep -u ci -a`, and `pgrep -a dockerd` all come back empty. Anything
      running there means stop again, don't copy.
- [ ] Final pass: same rsync with `--delete` (this also removes the new
      filesystems' `lost+found`, which is harmless).
- [ ] Unmount `/mnt/*`, `mv /srv/containerd /srv/containerd.old` (same for
      ci-docker), `mkdir` the empty mountpoints and `sudo chattr +i` them,
      so nothing can write into them while they're unmounted.
- [ ] fstab lines by `/dev/disk/by-id/dm-uuid-LVM-*` (match the existing
      style), **no `nofail`**. Then `sudo systemctl daemon-reload` and
      `sudo mount -a`.
- [ ] **Review focus #8:** make the services require their mounts, so a
      missing LV means the service doesn't start (instead of starting on the
      empty dir), and the box still boots with ssh:
      - `sudo systemctl edit containerd.service` and `docker.service`: add
        `[Unit]` `RequiresMountsFor=/srv/containerd`
      - `sudo systemctl edit user@2000.service`: add
        `RequiresMountsFor=/srv/ci-docker`
- [ ] Gate, not just a look: `stat -c '%U:%G %a' /srv/containerd /srv/containerd.old /srv/ci-docker /srv/ci-docker.old`
      must match pairwise (`/srv/ci-docker` owned by `ci`). Fix before
      starting anything.
- [ ] Start things back up (`user@2000.service`, docker, the service units,
      the timers), compare `docker ps` to the `preflight` list, and run a CI
      build to prove the rootless daemon works.
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
      mount by UUID (mountpoint up to the backup PR). `nofail` is right here,
      unlike the Docker LVs: it's an external disk, and a missing backup
      target shouldn't block boot.
- [ ] Second repo + schedule per `homelab/services/backup/README.md`; that
      PR owns the details.

## Rollback

What "go back" means at each point. Written out so a failure at 11pm doesn't
mean working it out from scratch.

| Failed during | State | Way back |
|---|---|---|
| `rehearsal-reboot` | Console changes only | Pick 146 from the GRUB menu if 147 is the problem. Otherwise nothing to undo |
| `preflight`, `partition-new` | Nothing changed | Re-enable timers (`enable --now`), done |
| `migrate-lvm`, before `vgreduce` | VG spans both disks | `pvmove ${NEW}-part3 ${OLD}-part4` for whatever moved, `vgreduce vg0 ${NEW}-part3` |
| `migrate-lvm`, after `pvremove` | VG only on PNY (USB), SanDisk empty | `pvcreate ${OLD}-part4`, `vgextend`, reverse `pvmove`, `vgreduce` the PNY |
| `boot-fixup`, `test-boot` | Boots from SanDisk entry by default | Restore `/etc/fstab.pre-swap`, `daemon-reload`, remount `/boot` + `/boot/efi` from the SanDisk, `grub-install` to it, `dpkg-reconfigure` back. Data rollback as the row above |
| `swap` (PNY won't boot internally) | PNY in bay, SanDisk in case | Put drives back as they were (PNY in case, SanDisk in bay). The `ubuntu-sandisk` entry boots the SanDisk's ESP and `/boot`, and root comes up from the PNY over USB. Debug from there |
| After `soak` | Rollback given up on purpose | Restore from the `preflight` tarball + restic |

## When it won't boot

Where it stops tells you which layer broke. All of this assumes the
`rehearsal-reboot` prep is in place (GRUB menu visible, emergency shell
open, live USB proven on this box). Keep this section and the new `/boot`
UUID on your phone during `test-boot` and `swap`.

| Stops at | You see | Do |
|---|---|---|
| Firmware | "No bootable device", or straight into BIOS setup | F2: is the drive listed at all? If not, reseat it. If it is, F10 and pick the PNY. The `EFI/BOOT/BOOTX64.EFI` fallback runs `fbx64`, which rebuilds the NVRAM entry |
| GRUB | `grub>` or `grub rescue>` | The ESP stub can't find `/boot` (**review focus #1**). Run the GRUB commands below, then fix the stub with `grub-install` once booted |
| initramfs | `(initramfs)` busybox prompt | `cat /proc/partitions` (is the disk seen at all? if not, it's a driver or cable problem), then `lvm vgchange -ay vg0` and `exit` |
| systemd | Emergency shell | `journalctl -xb`, usually a bad fstab line. Fix it, `systemctl daemon-reload`, `reboot` |
| Boots, but no ssh or missing containers | Login prompt on the console | Log in on the console, `systemctl --failed`, compare `docker ps` to the `preflight` list |
| None of that gets anywhere | | Live USB (the `rehearsal-reboot` steps), mount the LVs, fix from there. Or [Rollback](#rollback) |

GRUB by hand (fill in the UUID at `partition-new`):

```
grub> search --no-floppy --fs-uuid --set=root <new /boot uuid>
grub> configfile /grub/grub.cfg
```

If `configfile` fails too, boot the kernel directly:

```
grub> linux /vmlinuz root=/dev/mapper/vg0-root ro
grub> initrd /initrd.img
grub> boot
```

## Close-out

- [ ] Update `findings.md` open questions, `homelab/docs/homelab_03_host_setup.md`
      (disk layout), and the README's homelab line if it mentions disk size.
- [ ] Close `639457b8` and `b584df49`; capture any followups in taskwarrior.
