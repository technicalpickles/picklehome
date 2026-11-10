# Provision the SanDisk backup disk

Turn the old picklelab boot SSD (SanDisk SDSSDA120G, 111.8G, in the Ugreen USB
case) into a second local backup target, mounted at `/mnt/backup-sandisk`.

This runbook only prepares the disk and the mount. Writing a second restic
repo to it is a separate change to `homelab/services/backup/`.

## Why it looks like this

- **Outside `/srv`.** The point is isolation. A full `/srv` or a dead PNY must
  not take the second copy with it.
- **Plain ext4, no LVM.** One small disk, nothing to span or grow into.
- **`nofail`.** It is an external USB disk. A missing backup target must not
  block boot, unlike the Docker LVs.
- **Immutable empty mountpoint.** With the disk unplugged, a write to
  `/mnt/backup-sandisk` fails instead of quietly filling the root volume.

Decided 2026-11-10 during the disk swap. Background:
`docs/plans/2026-10-16-picklelab-disk-swap.md` ("Second backup target").

## Before you start

- The disk is plugged into picklelab. Check:
  `lsblk -o NAME,SIZE,TRAN,MODEL /dev/disk/by-id/usb-SanDisk_SDSSDA120G_133309278642-0:0`
  shows `111.8G usb SDSSDA120G`.
- Nothing from it is mounted and `sudo pvs` does not list it.
- You are at a terminal on picklelab with sudo. The sudo allowlist does not
  cover any of these commands, so an agent cannot run them.

Use the stable by-id link, never `/dev/sdb`. Device letters move between
boots. The PNY is 931.5G on `sata`, so the size and transport guard rules it
out.

```bash
OLD=/dev/disk/by-id/usb-SanDisk_SDSSDA120G_133309278642-0:0
lsblk -dno SIZE,TRAN "$OLD"
```

It must print `111.8G usb`. Anything else, stop.

## Steps

1. **Wipe the old signatures. Destructive.** Partitions first, so a new
   partition at the same offset cannot revive an old signature, then the disk.

   ```bash
   sudo wipefs -a "$OLD"-part* && sudo wipefs -a "$OLD"
   ```

2. **One GPT partition, then ext4.**

   ```bash
   sudo sgdisk -n1:0:0 -t1:8300 -c1:backup-sandisk "$OLD" && sudo partprobe "$OLD" && sudo udevadm settle && sudo mkfs.ext4 -m 1 -L backup-sandisk "$OLD"-part1
   ```

   **Verify:** the `-part1` by-id link appears after `udevadm settle`. If
   `mkfs` says the file does not exist, run `ls -l /dev/disk/by-id | grep
   SanDisk` and use the link it shows.

3. **Immutable mountpoint.**

   ```bash
   sudo mkdir /mnt/backup-sandisk && sudo chattr +i /mnt/backup-sandisk
   ```

4. **fstab by UUID.**

   ```bash
   echo "UUID=$(sudo blkid -s UUID -o value "$OLD"-part1) /mnt/backup-sandisk ext4 defaults,nofail,x-systemd.device-timeout=10 0 2" | sudo tee -a /etc/fstab
   ```

5. **Mount it.**

   ```bash
   sudo systemctl daemon-reload && sudo mount /mnt/backup-sandisk && df -h /mnt/backup-sandisk
   ```

   **Verify:** mounting over the immutable directory works (the Docker split
   relies on the same behaviour and it did on 2026-11-10).

## Check

- `findmnt /mnt/backup-sandisk` shows ext4 from the SanDisk, about 110G size.
- `sudo touch /mnt/backup-sandisk/x && sudo rm /mnt/backup-sandisk/x` works.
- Unmounted, `sudo touch /mnt/backup-sandisk/x` fails with "Operation not
  permitted". Do this once: `sudo umount /mnt/backup-sandisk`, try, then
  `sudo mount /mnt/backup-sandisk`.
- `systemctl --failed` is empty.
- A reboot with the disk unplugged still reaches a login (`nofail`).
  **Verify** this the first time the disk is unplugged on purpose.

## After this

1. Add `/mnt/backup-sandisk` to `FILESYSTEMS` in
   `homelab/services/disk_monitor/disk_monitor.py`.
2. Backup change: second restic repo, `mountpoint -q` check before writing it,
   alert if missing without failing the primary backup.

## Replacing the disk later

Repeat from "Before you start" with the new disk's by-id link, then change the
UUID in `/etc/fstab`. Restic repos on a replaced disk are gone, so re-init the
second repo and let the next nightly backup repopulate it.
