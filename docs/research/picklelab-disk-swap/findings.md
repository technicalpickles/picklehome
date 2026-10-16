# picklelab disk swap: 111GB SanDisk to 1TB PNY

Research (2026-10-16) into moving picklelab's contents onto a new external 1TB
SSD, then physically swapping it in as the internal drive. Backlog:
taskwarrior `639457b8` (disk swap), with `b584df49` (Docker LV split) and
`6885ef30` (build off-box) as sibling angles on the same disk pressure.

## TL;DR

The swap is physically viable. Both drives are 2.5" SATA SSDs, the NUC has one
2.5" SATA bay, and the new drive is already visible to picklelab over USB.
Copy online with LVM (`pvmove`), fix up boot, then do the one physical swap.
Nothing has been changed on picklelab yet. Everything below is read-only
observation.

## What's there

| | Internal (`sda`) | New (`sdb`) |
|---|---|---|
| Drive | SanDisk SSD Plus 120GB (SDSSDA-120G-G26) | PNY CS900 1TB (SSD7CS900-1TB-RB) |
| Form factor | 2.5" SATA 6Gb/s, 7.0mm | 2.5" SATA III |
| Attached via | SATA (internal bay) | Ugreen USB-SATA enclosure (Realtek `0bda:9201`) |
| Size in `lsblk` | 111.8G | 931.5G |
| State | In use | Blank: no partitions, no filesystem |

- The enclosure bridge masks the drive's serial (reads all zeros) and reports a
  generic "SATA SSD" model. The make/model above comes from the Amazon listing
  the drive was bought from, not from the host.
- The NUC6CAYB has only one 2.5" SATA bay and no NVMe/M.2 storage slot, so
  "swap" is the only way to get the bigger drive internal.

### Current layout of `sda`

- `sda1` 1G vfat, `/boot/efi`
- `sda2` 512M, GPT type "Linux filesystem", no filesystem signature, not
  mounted, not in fstab, no holders, not swap. Looks like a curtin leftover
  nothing uses; don't mirror it on `sdb`.
- `sda3` 1G ext4, `/boot`
- `sda4` 109G LVM PV in `vg0`:
  - `vg0-root` 30G ext4, `/` (28% used, 7.7G)
  - `vg0-srv` 70G ext4, `/srv` (75% used, 49G, 18G free)

`vg0` has <9G free on its single PV (`/dev/sda4`). Swap is a 3.7G file,
`/swap.img`, on root.

`/srv` holds Docker and containerd data plus the service state, so it's where
the pressure is. Breakdown from `disk-report` (2026-10-16): `containerd` 37G,
`data` 5.1G, `ci-docker` 3.7G, `backups` 3.7G, `docker` 91M. Main Docker has
9G of reclaimable images and 6.5G of build cache; the rootless CI daemon's
3.9G of images is 99% reclaimable.

### `/etc/fstab`

| Mount | Source | Survives `pvmove`? |
|---|---|---|
| `/` | `/dev/disk/by-id/dm-uuid-LVM-<vg uuid><lv uuid>` | Yes: VG/LV UUIDs don't change |
| `/srv` | same, `dm-uuid-LVM-...` | Yes |
| `/boot` | `UUID=238a1829-...` (ext4, `sda3`) | Only if the new fs keeps the UUID |
| `/boot/efi` | `UUID=4191-DFAD` (vfat, `sda1`) | Only if the new fs keeps the UUID |
| swap | `/swap.img` | Yes, it's a file on root |

So the LVM half of the move needs no fstab edits at all. Only `/boot` and
`/boot/efi` matter: either update fstab to the new UUIDs, or create the new
filesystems with the old UUIDs (`mkfs.ext4 -U`, `mkfs.vfat -i`) after the old
ones are out of the picture. Don't have two filesystems with the same UUID
attached at once.

## Plan sketch

1. Partition `sdb` to mirror `sda`: EFI, `/boot`, and one LVM partition taking
   the rest.
2. Copy EFI and `/boot` contents to the new partitions.
3. `pvcreate` the new LVM partition, `vgextend vg0`, `pvmove` off `sda4`,
   `vgreduce`. This runs online, no downtime.
4. Grow `root` and `srv`. Fold in the Docker LV split (`b584df49`) while the
   volume group has room, since that has its own downtime window.
5. Fix up boot: fstab UUIDs, `grub-install` to `sdb`, EFI boot entry. Test-boot
   from USB if the BIOS allows.
6. Physical swap (the only real downtime): pull the PNY from the Ugreen case,
   install it in the NUC, put the old SanDisk in the case.
7. Repurpose the SanDisk as a second local backup target: `nofail` fstab mount,
   second restic repo. See `homelab/services/backup/README.md`.

Why not Clonezilla (the original `639457b8` idea): the new drive is already
visible on the live system, so `pvmove` avoids taking the box down for the
copy. The cost is more manual boot fixup, which is where the risk sits.

## Open questions

- [x] What is `sda2`? Unused (see layout above). Skip it.
- [ ] PNY CS900 thickness: believed 7mm, not confirmed. The bay fits up to
      9.5mm so low risk.
- [ ] Does the Ugreen case open easily enough to swap drives without wrecking
      it?
- [ ] BIOS: can the NUC6CAYB boot from the USB-attached `sdb` for a pre-swap
      test? And does it boot reliably after the swap with the EFI entry
      rewritten? (Fallback path `\EFI\BOOT\BOOTX64.EFI` on the new ESP is the
      safety net.)
- [x] Full `/etc/fstab` and LVM state: captured above. No sudo needed,
      `sudo -n /usr/local/sbin/disk-report` is on the passwordless list and
      prints `vgs`/`lvs`/`pvs`.
- [ ] Sizing: how big should `srv` and a new Docker LV be, and how much to
      leave unallocated in `vg0`?
- [ ] Expected downtime for the swap itself, plus the ~15 containers coming
      back up.
- [ ] Do backups (restic repo on local SSD) move cleanly with `/srv`, and is a
      fresh backup taken right before the swap?

## Access constraints

Most of the steps need root: `sfdisk`, `pvcreate`/`vgextend`/`pvmove`,
`grub-install`. None are on picklelab's passwordless sudo list
(`homelab/config/sudoers-deploy-ops`), and a non-interactive `ssh picklelab
"sudo ..."` fails. Options: run the one-off session with `ssh -t` and a human
typing the password, or widen the allowlist (a sudoers change on a prod host,
so Josh's call). Leaning interactive for a one-time job.

## Next steps

- Capture the missing read-only data (fstab, LVM state, `sda2`) in an
  interactive session.
- Decide the sizing and the Docker-LV fold-in.
- Turn this into an implementation plan in `docs/plans/` once the open
  questions are settled.
