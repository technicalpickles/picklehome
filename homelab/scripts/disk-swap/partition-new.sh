#!/usr/bin/env bash
# Partition new: GPT with ESP, /boot, and an LVM partition on the PNY.
# DESTRUCTIVE to $NEW only. Run with NEW set, after load-test.sh.
set -euo pipefail
source "$(dirname "$0")/lib.sh"

# Check every tool before the first destructive step, so a missing one stops us early.
command -v sgdisk >/dev/null || { echo "sgdisk missing: sudo apt-get install gdisk" >&2; exit 1; }
command -v mkfs.vfat >/dev/null || { echo "mkfs.vfat missing: sudo apt-get install dosfstools" >&2; exit 1; }
require_new_disk

sudo sgdisk -n1:0:+1G -t1:ef00 -n2:0:+1G -t2:8300 -n3:0:0 -t3:8e00 "$NEW"
sudo udevadm settle
for n in 1 2 3; do
  for _ in $(seq 20); do [ -e "${NEW}-part$n" ] && break; sleep 0.5; done
  [ -e "${NEW}-part$n" ] || { echo "${NEW}-part$n never appeared" >&2; exit 1; }
done

sudo mkfs.vfat -F32 "${NEW}-part1"
sudo mkfs.ext4 -L boot "${NEW}-part2"

lsblk -f "$NEW"
echo "new /boot UUID (for the 'When it won't boot' cheat sheet): $(sudo blkid -s UUID -o value "${NEW}-part2")"
