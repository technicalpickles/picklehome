# picklelab disk swap: 111GB SanDisk to 1TB PNY

> Ops runbook, not a code plan. Almost every stage is a root shell on
> picklelab in an interactive `ssh -t picklelab` session with Josh typing the
> sudo password. The only code change is Disk monitor mounts. Stages have
> names, not numbers. Each heading's anchor (`#soak`, `#docker-split`) is the
> stable thing to cite in commits and tasks.
>
> **Where commands run:** a root-capable shell on picklelab (`ssh -t picklelab`,
> or the console) unless the step says otherwise. `just ...` recipes run on
> the Mac from this repo. They ssh to picklelab themselves.
>
> **Destructive commands** (ones that overwrite a disk or delete data) are
> marked **Destructive** with a guard to run first and the reason they're
> safe at that point. If the guard doesn't match, stop.

**Goal:** picklelab runs from the 1TB PNY in the internal bay, with Docker
churn on its own LVs and the old SanDisk repurposed as a second backup target.

**Approach:** Copy online with LVM (`pvmove`) while the PNY sits in the USB
enclosure, fix up boot, prove it boots from the new ESP, then do one physical
swap. Grow and split LVs only after the swap has soaked.

**Research:** [`docs/research/picklelab-disk-swap/findings.md`](../research/picklelab-disk-swap/findings.md)
(layout, fstab, open questions). Backlog: taskwarrior `639457b8` (swap),
`b584df49` (Docker LV split), `6885ef30` (build off-box, unaffected),
`b1c53be5` (disk_monitor latent bugs, same file as Disk monitor mounts).

## Stages at a glance

In order. Each one is a checklist [below](#stages), done by hand.

| Stage | What it does | Downtime |
|---|---|---|
| [Rehearsal reboot](#rehearsal-reboot) | Boot the pending kernel, prep console access, prove the live USB works | ~15 min |
| [Preflight](#preflight) | Pause timers, back up off-box, health- and load-test the PNY | none |
| [Partition new](#partition-new) | Partition and format the PNY | none |
| [Migrate LVM](#migrate-lvm) | `pvmove` root and srv onto the PNY while running | none (runs for a while) |
| [Boot fixup](#boot-fixup) | Copy `/boot` and the ESP, point GRUB and fstab at the PNY | none |
| [Test boot](#test-boot) | Prove the PNY boots on its own, SanDisk still the fallback | two short reboots |
| [Swap](#swap) | Physically put the PNY in the bay | ~15-20 min |
| [Soak](#soak) | Run a few days on the PNY, then turn timers back on. Ends the easy rollback | none |
| [Disk monitor mounts](#disk-monitor-mounts) | Code PR so disk alerts cover the new LVs. Any time before Docker split | none |
| [Docker split](#docker-split) | Move containerd and CI Docker onto their own LVs | a few minutes |
| [Grow](#grow) | Grow root and srv | none |
| [Second backup target](#second-backup-target) | Reuse the SanDisk as a second restic repo | none |

## Terms

- **ESP** (EFI System Partition): the small vfat partition mounted at
  `/boot/efi`. The firmware reads bootloaders (`shimx64.efi`, `grubx64.efi`)
  from it. Each disk here has its own.
- **PV / VG / LV** (LVM): a physical volume is a partition handed to LVM.
  PVs pool into a volume group (`vg0`), and logical volumes (`root`, `srv`)
  are carved out of the group. `pvmove` relocates an LV's data from one PV to
  another while it's mounted and in use.
- **NVRAM boot entry**: a `BootXXXX` record in the firmware (list them with
  `efibootmgr`). Each one names a disk partition and a `.efi` file. `BootOrder`
  is the order they're tried; `BootNext` is a one-shot override for the next
  boot only.
- **Fallback path**: `EFI/BOOT/BOOTX64.EFI` on an ESP. The firmware tries it
  when no NVRAM entry matches, for example after the disk moves to a
  different port.
- **debconf**: Debian's stored answers to package install questions. grub's
  answer says which ESP to reinstall to when grub itself is upgraded.
- **by-id**: `/dev/disk/by-id/` names, built from the drive's model and serial.
  Unlike `sda`/`sdb`, they don't change when other drives come and go, but
  they *do* change when a drive moves between USB and SATA (the `usb-` or
  `ata-` prefix).

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
  and becomes `sda` after the swap. Commands below use `$NEW` (the PNY) and
  `$OLD` (the SanDisk). They're plain shell variables, so **set them at the
  start of every shell** (a new ssh session, tmux window, or `sudo -i` starts
  without them):

  ```bash
  ls -l /dev/disk/by-id/ | grep -v part   # find the two whole-disk links
  NEW=/dev/disk/by-id/usb-PNY_...-0:0     # the PNY, while it's in the enclosure
  OLD=/dev/disk/by-id/ata-SanDisk_...     # the SanDisk, while it's internal
  lsblk -dno SIZE,TRAN "$NEW" "$OLD"      # guard: 931.5G usb, then 111.8G sata
  ```

  If the guard shows anything else, the variables are wrong: stop. Both links
  change when a drive changes connection. After Swap, the PNY becomes
  `ata-...` and the SanDisk (once it's in the enclosure) becomes `usb-...`.
  Don't paste the full by-id names (they contain serials) into anything
  committed.
- **Never have two filesystems with the same UUID attached.** So no `dd` of
  partitions: make new filesystems and update fstab and grub to match.
- **No LV grows or new LVs until Soak passes.** Until then `vg0` fits on
  the SanDisk (100G allocated, 109G PV), so a reverse `pvmove` is possible.
  See [Rollback](#rollback).
- **Automatic upgrades stay paused from Preflight until Soak ends.** A
  kernel or grub update landing mid-migration writes to whichever `/boot` and
  ESP happen to be mounted, and can leave the two disks disagreeing. Pause
  with `systemctl disable --now`, not `stop`: the timers are all `enabled`,
  so a plain `stop` is undone by the first reboot in Test boot.
- **`systemctl daemon-reload` after every fstab edit**, or systemd keeps
  stale mount units.
- Sudo is interactive (`ssh -t`). Don't widen `homelab/config/sudoers-deploy-ops`
  for this.

## Review focus

Ways this goes wrong that no step "tests" by default. Each one has a check in
the stage that owns it.

1. **Boot fixup is incomplete.** Ubuntu's ESP stub (`EFI/ubuntu/grub.cfg`)
   finds `/boot` by filesystem UUID. Copy the ESP without re-running
   `grub-install`, and the new ESP keeps pointing at the *old* `/boot`, which
   is gone after the swap: you get a grub rescue prompt. Check is in
   Boot fixup.
2. **Backups cover less than the box.** restic backs up `/srv/data` only. Its
   repo lives on the disk being migrated, and once `pvmove` finishes the
   SanDisk is no longer a copy of anything (its extents are freed). `/etc`,
   `/var/lib/tailscale`, `/srv/docker/volumes`, and the `ci` user's config
   aren't backed up at all. Preflight takes an off-box copy of all of it.
3. **disk_monitor goes blind after the split.** It hardcodes
   `FILESYSTEMS = ["/", "/srv"]` and uses `du -x /srv`, so the new LVs (the
   ones most likely to fill) would never alert. Ship Disk monitor mounts
   before Docker split.
4. **Something writes during the Docker copy.** The rootless CI daemon runs
   under `user@2000.service`, separate from system Docker. And
   `docker-prune.sh` and `disk-report.sh` run `sudo -iu ci docker ...`,
   which opens a PAM session that respawns `user@2000` (linger is on). Stop
   the timers too, and re-check right before the final rsync.
5. **`grub-install` deletes the SanDisk's boot entry.** It removes every
   NVRAM entry with the same label (`ubuntu`) and puts the new one first. So
   without extra work there's no "SanDisk still bootable" fallback during
   Test boot. Boot fixup recreates it under another label.
6. **debconf still points grub at the SanDisk's ESP.** Confirmed:
   `grub-efi/install_devices` is the SanDisk's `scsi-0ATA_SanDisk_*-part1`.
   The next grub or shim upgrade would then fail its postinst (leaving dpkg
   half-configured) or install to the wrong disk. Re-pointed in Boot fixup
   and again in Swap, since the PNY's by-id changes from `usb-*` to `ata-*`.
7. **The USB bridge resets under sustained I/O.** The PNY is on the `uas`
   driver (Realtek `0bda:9201`). From Migrate LVM to Swap, root and
   `/srv` live on USB. A UAS reset there means I/O errors and ext4 going
   read-only, possibly mid-`pvmove`. Preflight load-tests it, and the
   gap between Migrate LVM and Swap should be the same day.
8. **A new LV doesn't mount at boot.** A plain fstab line that fails drops a
   headless box into emergency mode (no ssh). `nofail` is worse: Docker
   starts on the empty mountpoint dir and quietly refills `/srv`.
   Docker split uses `RequiresMountsFor=` plus an immutable empty
   mountpoint.
9. **The swap fails and there's no written way back.** See
   [Rollback](#rollback).
10. **The first reboot tests two things at once.** The box is running
    `6.8.0-146` but `6.8.0-147` was installed on 2026-10-14 and
    `/boot/initrd.img` already points at it. If Test boot is the first
    reboot, a failure could be the new kernel or the new disk.
    Rehearsal reboot boots 147 on the SanDisk first.
11. **A boot failure has no way in from the console.** GRUB is
    `GRUB_TIMEOUT_STYLE=hidden` / `GRUB_TIMEOUT=0` (no menu, no older kernel,
    no recovery entry), the firmware boot timeout is 1 second, and there's
    no drop-in on `emergency.service`. Ubuntu locks root by default, so a
    failed fstab mount ends at "root account is locked", not a shell.
    Rehearsal reboot opens all of these up for the migration window, and
    Soak closes them again. See [When it won't boot](#when-it-wont-boot).

Already checked and fine (2026-10-16):
- Both drives report 512-byte logical sectors over USB, so the GPT survives
  the move to native SATA.
- Secure Boot is disabled.
- The initramfs includes `uas` and `usb-storage`, so root-on-USB-LVM boots
  for Test boot.
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

### Rehearsal reboot

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
- [ ] **Open up the emergency shell.** Run `sudo systemctl edit emergency.service`,
      and in the editor it opens, add:

      ```ini
      [Service]
      Environment=SYSTEMD_SULOGIN_FORCE=1
      ```

      Do the same for `rescue.service`. A failed mount now drops to a root
      shell on the console instead of "root account is locked". Safe because
      it only affects the physical console, and anyone at the keyboard
      already has root via a live USB. It's a drop-in file under
      `/etc/systemd/system/<unit>.d/`, so Soak removes it cleanly. Also run
      `sudo passwd -S root` and note whether root is locked (`L`).
- [ ] **Make GRUB visible.** Create `/etc/default/grub.d/99-disk-swap.cfg`
      containing:

      ```sh
      GRUB_TIMEOUT_STYLE=menu
      GRUB_TIMEOUT=5
      ```

      then `sudo update-grub`. Files in `grub.d/` are read after
      `/etc/default/grub`, so these two lines win without editing the main
      file. That gets you a 5s menu with the older kernel and recovery mode.
      GRUB recovery mode is how the lost install password got reset, so that
      path has worked here before.
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
      Test boot fallback question). Boot it.
- [ ] In the live shell: `lvm vgchange -ay vg0`,
      `mount -o ro /dev/vg0/root /mnt`, `ls /mnt/etc`, then `umount /mnt`
      and `lvm vgchange -an vg0`. That proves the rescue path works on this
      hardware before you need it.
- [ ] Pull the stick and reboot. It comes back normally on the SanDisk.
- [ ] Record the BIOS findings in `findings.md` (USB in F10: yes/no,
      Fast Boot, Legacy/CSM).

### Preflight

Nothing here touches the SanDisk's data: pausing timers, backups, a package
install, a Docker prune, and tests that write only to the blank PNY.

- [ ] Set `$NEW` and `$OLD` and run the guard (see
      [Global constraints](#global-constraints)). Also confirm the PNY has no
      partitions: `lsblk $NEW` shows one line, no children.
- [ ] Pause anything that writes on a schedule:
      `sudo systemctl disable --now apt-daily.timer apt-daily-upgrade.timer unattended-upgrades docker-prune.timer backup.timer`.
      `disable`, not `stop`, so they stay off through the reboots in
      Test boot and Swap. They stay off until Soak (backups run by
      hand with `just backup-now` in between). Check with
      `systemctl list-unit-files <same list>`: all `disabled`.
- [ ] Run a fresh backup (on the Mac): `just backup-now`, then
      `just backup-snapshots` shows one from today.
- [ ] Prune so less gets copied and there's room for the tarball:
      `sudo /opt/homelab/homelab/services/disk-hygiene/docker-prune.sh`
      (up to ~16G). It's the same script the weekly timer runs: dangling
      images and build cache only, never `-a` or `--volumes`, so nothing a
      running or stopped container needs.
- [ ] Copy off-box everything the box can't rebuild from the repo:
      `/srv/backups/restic`, `/etc`, `/var/lib/tailscale`,
      `/srv/docker/volumes`, `/home/ci/.config`. Check the size first
      (`sudo du -sch <paths>`) against `df -h /srv`, then write it on
      picklelab and pull it from the Mac, so picklelab never needs ssh access
      back to the Mac.

      ```bash
      # on picklelab
      sudo tar -cf /srv/pre-swap.tar <paths> && sudo chown "$USER" /srv/pre-swap.tar
      # on the Mac
      scp picklelab:/srv/pre-swap.tar ~/picklelab-pre-swap-2026-10-XX.tar
      tar -tf ~/picklelab-pre-swap-2026-10-XX.tar | cut -d/ -f1-3 | sort -u
      # back on picklelab, once the Mac copy lists all five
      rm /srv/pre-swap.tar
      ```

      Done when the Mac copy lists all five paths. It holds secrets
      (Tailscale node key, `/etc/shadow`), so keep it out of synced folders
      and delete it after Soak.
- [ ] Save metadata off-box too: `sudo vgcfgbackup -f /tmp/vg0.vgcfg vg0`
      (LVM's description of `vg0`, for rebuilding it by hand),
      `sudo sgdisk --backup=/tmp/sandisk.gpt $OLD` (a copy of the SanDisk's
      partition table; both are read-only on the disk), `sudo efibootmgr -v`,
      `sudo disk-report`, `cat /etc/fstab`, and the container list
      (`docker ps --format '{{.Names}}' | sort`, which is what later stages
      compare against). `scp` them to the Mac the same way.
- [ ] **SMART health on the PNY.** `smartctl` isn't installed:
      `sudo apt-get install smartmontools` (on the passwordless list). Then
      `sudo smartctl -d sat -H -A $NEW` (passed, zero reallocated/pending
      sectors) and `sudo smartctl -d sat -t short $NEW`, with the result in
      `-l selftest` a few minutes later. If the bridge won't pass SMART
      through, note it and rely on the load test.
- [ ] **Load-test the USB bridge (review focus #7)** while the PNY is still
      blank. **Destructive** to whatever `$NEW` points at: it writes 30GB of
      zeros over the start of the disk. Guard: rerun
      `lsblk -dno SIZE,TRAN "$NEW"` right before and see `931.5G usb`. Safe
      because the PNY is blank, and it has to happen before Partition new
      for the same reason. If `$NEW` were the SanDisk, this would wipe the
      running system, hence the guard.

      ```bash
      sudo dd if=/dev/zero of="$NEW" bs=1M count=30000 oflag=direct status=progress
      sudo dmesg | grep -iE 'uas|reset|abort'
      ```

      Pass is no resets and a steady rate. If it resets, stop. Either add the
      `usb-storage.quirks=0bda:9201:u` kernel arg (makes this enclosure use
      the older `usb-storage` driver instead of `uas`; needs a reboot) and
      re-test, or switch to an offline copy: boot the live USB and copy with
      the box down, the Clonezilla-style approach `findings.md` considered
      first.

### Partition new

**Destructive** to `$NEW` only. Guard: `lsblk -dno SIZE,TRAN "$NEW"` shows
`931.5G usb`. Safe because the PNY holds nothing but the load test's zeros.

- [ ] `sudo sgdisk -n1:0:+1G -t1:ef00 -n2:0:+1G -t2:8300 -n3:0:0 -t3:8e00 "$NEW"`
      writes a fresh GPT with the three partitions from
      [Target layout](#target-layout) (`ef00` ESP, `8300` Linux, `8e00` LVM).
      Then `sudo udevadm settle`, so the `${NEW}-partN` links exist before
      the next step uses them.
- [ ] `sudo mkfs.vfat -F32 ${NEW}-part1`, `sudo mkfs.ext4 -L boot ${NEW}-part2`.
      New filesystems get new UUIDs, which is the point (see the
      no-duplicate-UUIDs rule in [Global constraints](#global-constraints)).
- [ ] Verify: `lsblk -f $NEW` shows vfat / ext4 / no fs on part3.
- [ ] Fill in the [When it won't boot](#when-it-wont-boot) cheat sheet with
      the new `/boot` UUID (`blkid -s UUID -o value ${NEW}-part2`) and keep
      it somewhere you can read it while the box is down (your phone, not
      picklelab).

### Migrate LVM

Online, no downtime. Runs for a while (~100G over USB 3). Run it under
`tmux` or `screen` so a dropped ssh doesn't matter.

- [ ] `sudo pvcreate ${NEW}-part3 && sudo vgextend vg0 ${NEW}-part3`.
      This labels the PNY's third partition as a PV and adds it to `vg0` as
      empty space. Nothing moves yet, and `vgreduce` undoes it.
- [ ] Move one LV at a time so an abort only strands one of them:
      `sudo pvmove -i 60 -n root ${OLD}-part4 ${NEW}-part3`, then the same
      with `-n srv` (`-i 60` prints progress every 60s).
      Why this is safe on a live system: `pvmove` mirrors each chunk to the
      new PV, switches the LV over to the copy, and only then frees the old
      chunk, checkpointing in LVM metadata as it goes. A crash or dropped ssh
      leaves every chunk on one disk or the other, never neither. A bare
      `sudo pvmove` resumes. `sudo pvmove --abort` stops only the segment in
      flight. Anything already moved stays on the PNY, which is fine because
      it's all one VG either way.
- [ ] Verify: `sudo pvs` shows `${OLD}-part4` with PFree == PSize (fully
      empty).
- [ ] `sudo vgreduce vg0 ${OLD}-part4 && sudo pvremove ${OLD}-part4`.
      `vgreduce` takes the SanDisk out of `vg0`, and refuses if anything is
      still allocated on it, so it doubles as a check. `pvremove` wipes the
      LVM label. That matters: without it, the SanDisk carries a stale `vg0`
      label that collides with the real one when it goes back into the
      enclosure. This is the point where the SanDisk stops being a copy of
      anything.
- [ ] No fstab change needed: `/` and `/srv` mount by `dm-uuid-LVM-*`, which
      `pvmove` doesn't change. Confirm with `findmnt / /srv`.

### Boot fixup

Do the `/boot` copy and the mount switch back to back, so nothing can land
in between (upgrades are paused anyway).

- [ ] Copy `/boot`: mount `${NEW}-part2` at `/mnt/newboot`,
      `sudo rsync -aHAXx /boot/ /mnt/newboot/`. The `-x` keeps rsync from
      descending into the `/boot/efi` mount, so the copy gets an empty `efi`
      dir to mount the new ESP on.
- [ ] Copy the ESP: mount `${NEW}-part1` at `/mnt/newefi`,
      `sudo rsync -rt /boot/efi/ /mnt/newefi/`.
- [ ] Switch the live mounts: unmount `/mnt/*`, `umount /boot/efi /boot`,
      `sudo cp /etc/fstab /etc/fstab.pre-swap`, then edit the `/boot` and
      `/boot/efi` lines in `/etc/fstab` to the new UUIDs
      (`blkid ${NEW}-part1 ${NEW}-part2`). Leave the other lines alone.
      `sudo systemctl daemon-reload`, `sudo mount -a`, then
      `findmnt /boot /boot/efi` shows the PNY's partitions.
      Why unmounting `/boot` on a running box is safe: the running kernel is
      already in memory, and `/boot` is only read at boot or written by
      kernel and grub upgrades, which are paused. If `mount -a` fails, the
      old lines are in `fstab.pre-swap`, and the SanDisk's partitions are
      untouched.
- [ ] `sudo grub-install --target=x86_64-efi --efi-directory=/boot/efi --bootloader-id=ubuntu`
      and `sudo update-grub`. `grub-install` writes into whatever ESP is
      mounted at `/boot/efi` (the PNY's now, after the step above) and
      creates an NVRAM entry for it. `update-grub` rewrites
      `/boot/grub/grub.cfg` on the PNY's `/boot`. Neither touches the
      SanDisk's partitions, since they're no longer mounted.
- [ ] **Review focus #1 check:** `grep -i uuid /boot/efi/EFI/ubuntu/grub.cfg`
      shows the *new* `/boot` UUID, not the SanDisk's (the old `/boot` line in
      `/etc/fstab.pre-swap`, `238a1829-...`).
- [ ] **Review focus #5:** `grub-install` just deleted the SanDisk's `ubuntu`
      entry. Recreate it:
      `sudo efibootmgr -c -d "$OLD" -p 1 -L ubuntu-sandisk -l '\EFI\ubuntu\shimx64.efi'`
      (`-d`/`-p` name the SanDisk's partition 1, its ESP; `-l` is the shim
      file on it, the same file the original entry pointed at). This only
      adds an NVRAM record, nothing on disk changes.
      Then set the order. Run `sudo efibootmgr`, find the `BootXXXX` numbers
      for `ubuntu-sandisk` and the new `ubuntu` (the PNY), and run
      `sudo efibootmgr -o <sandisk>,<pny>,<every other existing number>`.
      Keep the others, including the firmware's own `SATA : PORT 0` entry,
      at the end, so nothing disappears from the F10 menu. Now the SanDisk is
      the default, and the PNY is only tried when asked. The SanDisk's
      `/boot` (`sda3`) is frozen at copy time, which is fine as long as
      upgrades stay paused.
- [ ] **Review focus #6:** `sudo dpkg-reconfigure grub-efi-amd64-signed`
      (or `grub-efi-amd64`, whichever owns the question on this box). On this
      minimized install there's no `dialog` package, so it asks as a plain
      text prompt with numbered choices (see `homelab_03_host_setup.md`).
      Pick only the PNY's ESP: the `usb-PNY_...-part1` path. It may also
      reinstall grub to the ESP you pick, which is the same thing the
      `grub-install` above did. Verify with
      `sudo debconf-show grub-efi-amd64 | grep install_devices`.
- [ ] Confirm the fallback path is on the new ESP: `/boot/efi/EFI/BOOT/`
      has `BOOTX64.EFI` and `fbx64.efi`, and `/boot/efi/EFI/ubuntu/BOOTX64.CSV`
      exists (`fbx64` uses it to rebuild a missing NVRAM entry).

### Test boot

Two reboots, a few minutes each. Proves the PNY boots on its
own while the SanDisk is still internal and is the default.

- [ ] NVRAM path: `sudo efibootmgr -n <pny entry>` (the `ubuntu` entry's
      number from `sudo efibootmgr`), then reboot. Why this is safe:
      `BootNext` applies to one boot only. The firmware clears it as soon as
      it uses it, so if the PNY fails, the next power cycle follows
      `BootOrder` back to the SanDisk. After: `findmnt /boot/efi` is the PNY's
      part1, and containers come back (compare to the Preflight list).
- [ ] Removable fallback path: reboot and pick the PNY's generic or USB
      entry from the F10 boot menu, which uses `EFI/BOOT/BOOTX64.EFI`.
      Same checks. If the BIOS won't offer USB here, note it. In that case the
      fallback only gets tested for real during Swap.
- [ ] If either path *tries* and fails, reboot with nothing chosen: BootOrder
      lands on the SanDisk entry, and you debug from there.
- [ ] Once both pass: `sudo efibootmgr -o <pny>,<sandisk>,...` so the PNY is
      the default going into the swap.

### Swap

The real downtime: shut down, move drives, boot. Expect ~15-20 minutes
including ~20 containers coming back. Same day as Migrate LVM if possible,
to keep root off USB for as little time as possible.

- [ ] Final `docker ps` list, then `sudo shutdown -h now`.
- [ ] Pull the PNY out of the Ugreen case, SanDisk out of the NUC bay, PNY
      into the bay. SanDisk goes in the Ugreen case but **stays unplugged**
      for now.
- [ ] Power on. If it doesn't find a boot entry, pick the PNY from the F10
      boot menu.
- [ ] Verify: `lsblk` shows the PNY as `sda` with all mounts, `docker ps`
      matches the Preflight list, `just disk-monitor-check` is quiet,
      Tailscale Services resolve.
- [ ] Re-point debconf at the PNY's new `ata-*` ESP path
      (`dpkg-reconfigure` as in Boot fixup), and remove the dead
      `ubuntu-sandisk` NVRAM entry (`efibootmgr -b <num> -B`). Deleting it
      only removes the NVRAM record, not anything on a disk. Do it only after
      the verify step above passes: until then it's the Rollback path.
- [ ] `$NEW` and `$OLD` are stale from here on (see
      [Global constraints](#global-constraints)). Re-set `NEW` to the PNY's
      `ata-...` link before anything else uses it.

### Soak

- [ ] Leave it a few days, with `just backup-now` run by hand nightly-ish
      while the timers are paused.
- [ ] Undo the console changes from Rehearsal reboot:
      `sudo systemctl revert emergency.service rescue.service` (removes all
      local overrides on those units; ours are the only ones, there were none
      on 2026-10-16),
      `sudo rm /etc/default/grub.d/99-disk-swap.cfg && sudo update-grub`.
      Keep the 5s firmware timeout if you like it.
- [ ] Then re-enable everything paused in Preflight
      (`sudo systemctl enable --now ...` for the same list), and watch one
      unattended-upgrades run, one nightly backup, and one weekly prune
      succeed. A grub or shim upgrade in this window is the real test of the
      debconf fix.
- [ ] After this, the reverse-`pvmove` rollback is deliberately given up.

### Disk monitor mounts

Code change, its own PR (taskwarrior `9fd7f741`). Can land any time before
Docker split.

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

### Docker split

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
      after Soak), the systemd units for the compose stacks,
      `sudo systemctl stop docker docker.socket containerd`, and
      `sudo systemctl stop user@2000.service`.
- [ ] Immediately before the final pass, check that `pgrep -a containerd`,
      `pgrep -u ci -a`, and `pgrep -a dockerd` all come back empty. Anything
      running there means stop again, don't copy.
- [ ] Final pass: same rsync with `--delete` (this also removes the new
      filesystems' `lost+found`, which is harmless).
- [ ] Unmount `/mnt/*`, `mv /srv/containerd /srv/containerd.old` (same for
      ci-docker), `mkdir` the empty mountpoints and `sudo chattr +i` them,
      so nothing can write into them while they're unmounted. The immutable
      flag is on the empty directory underneath. Mounting the LV over it
      still works, and writes go to the LV. `sudo chattr -i` undoes it if the
      directory ever needs changing.
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
      the timers), compare `docker ps` to the Preflight list, and run a CI
      build to prove the rootless daemon works.
- [ ] After a day of normal running: `sudo rm -rf /srv/containerd.old /srv/ci-docker.old`.
      **Destructive.** Guard: `findmnt /srv/containerd /srv/ci-docker` shows
      both LVs mounted, and Docker and CI have run fine for that day. Safe
      because these are the pre-split copies. The live data is on the LVs.

### Grow

Online, no downtime.

- [ ] `sudo lvextend -r -L 50G vg0/root` and `sudo lvextend -r -L 100G vg0/srv`
      (`-r` resizes the ext4 too).
- [ ] `sudo vgs` shows ~600G free; `disk-report` looks like the target layout table.

### Second backup target

The old SanDisk becomes a second local restic repo (`639457b8`'s last part).
Small enough to fold in here, but its details belong to the backup service,
so it gets its own PR touching `homelab/services/backup/`.

- [ ] Plug the Ugreen case in. `lsblk` shows the SanDisk with its old
      partitions and no LVM label (the `pvremove` in Migrate LVM).
- [ ] Re-set `OLD`: in the enclosure, the SanDisk is a `usb-...` link now,
      not the `ata-SanDisk_...` one from before. Guard:
      `lsblk -dno SIZE,TRAN "$OLD"` shows `111.8G usb`,
      `lsblk -o NAME,MOUNTPOINTS "$OLD"` shows nothing mounted, and
      `sudo pvs` doesn't list it. Safe because
      the SanDisk has held nothing since Migrate LVM, and the guard rules out
      pointing at the PNY (931.5G, sata).
- [ ] **Destructive:** `sudo wipefs -a "$OLD"` (erases the old partition
      table and filesystem signatures), then a single GPT partition, ext4, `nofail` fstab
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
| Rehearsal reboot | Console changes only | Pick 146 from the GRUB menu if 147 is the problem. Otherwise nothing to undo |
| Preflight, Partition new | Nothing changed | Re-enable timers (`enable --now`), done |
| Migrate LVM, before `vgreduce` | VG spans both disks | `pvmove ${NEW}-part3 ${OLD}-part4` for whatever moved, `vgreduce vg0 ${NEW}-part3` |
| Migrate LVM, after `pvremove` | VG only on PNY (USB), SanDisk empty | `pvcreate ${OLD}-part4`, `vgextend`, reverse `pvmove`, `vgreduce` the PNY |
| Boot fixup, Test boot | Boots from SanDisk entry by default | Restore `/etc/fstab.pre-swap`, `daemon-reload`, remount `/boot` + `/boot/efi` from the SanDisk, `grub-install` to it, `dpkg-reconfigure` back. Data rollback as the row above |
| Swap (PNY won't boot internally) | PNY in bay, SanDisk in case | Put drives back as they were (PNY in case, SanDisk in bay). The `ubuntu-sandisk` entry boots the SanDisk's ESP and `/boot`, and root comes up from the PNY over USB. Debug from there |
| After Soak | Rollback given up on purpose | Restore from the Preflight tarball + restic |

## When it won't boot

Where it stops tells you which layer broke. All of this assumes the
Rehearsal reboot prep is in place (GRUB menu visible, emergency shell
open, live USB proven on this box). Keep this section and the new `/boot`
UUID on your phone during Test boot and Swap.

| Stops at | You see | Do |
|---|---|---|
| Firmware | "No bootable device", or straight into BIOS setup | F2: is the drive listed at all? If not, reseat it. If it is, F10 and pick the PNY. The `EFI/BOOT/BOOTX64.EFI` fallback runs `fbx64`, which rebuilds the NVRAM entry |
| GRUB | `grub>` or `grub rescue>` | The ESP stub can't find `/boot` (**review focus #1**). Run the GRUB commands below, then fix the stub with `grub-install` once booted |
| initramfs | `(initramfs)` busybox prompt | `cat /proc/partitions` (is the disk seen at all? if not, it's a driver or cable problem), then `lvm vgchange -ay vg0` and `exit` |
| systemd | Emergency shell | `journalctl -xb`, usually a bad fstab line. Fix it, `systemctl daemon-reload`, `reboot` |
| Boots, but no ssh or missing containers | Login prompt on the console | Log in on the console, `systemctl --failed`, compare `docker ps` to the Preflight list |
| None of that gets anywhere | | Live USB (the Rehearsal reboot steps), mount the LVs, fix from there. Or [Rollback](#rollback) |

GRUB by hand (fill in the UUID at Partition new):

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
