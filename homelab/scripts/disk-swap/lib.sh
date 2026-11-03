# shellcheck shell=bash
# Shared guard for the disk-swap scripts. Source it, don't run it.
# See docs/plans/2026-10-16-picklelab-disk-swap.md ("Global constraints").

# Refuses unless $NEW is the blank-ish, unmounted, USB-attached 1TB-class disk.
# Anything else (the SanDisk, a partition, an unset variable) stops here.
require_new_disk() {
  : "${NEW:?set NEW to the PNY usb by-id link first, and export it}"
  [ -e "$NEW" ] || { echo "NEW does not exist: $NEW" >&2; exit 1; }

  local real size tran mounts parts
  real=$(readlink -f "$NEW")
  size=$(lsblk -dnbo SIZE "$real")
  tran=$(lsblk -dno TRAN "$real" | tr -d ' ')
  parts=$(lsblk -nro TYPE "$real" | grep -c '^part$' || true)
  mounts=$(lsblk -nro MOUNTPOINTS "$real" | grep -c . || true)

  [ "$(lsblk -dno TYPE "$real" | tr -d ' ')" = disk ] || { echo "NEW is not a whole disk" >&2; exit 1; }
  [ "$tran" = usb ] || { echo "NEW transport is '$tran', expected usb" >&2; exit 1; }
  [ "$size" -ge 900000000000 ] || { echo "NEW is only $size bytes, expected ~1TB" >&2; exit 1; }
  [ "$mounts" -eq 0 ] || { echo "NEW has mounted filesystems, refusing" >&2; exit 1; }
  REQUIRE_PARTS=${REQUIRE_PARTS:-0}
  [ "$parts" -eq "$REQUIRE_PARTS" ] || { echo "NEW has $parts partitions, expected $REQUIRE_PARTS" >&2; exit 1; }

  echo "About to write to:"
  lsblk -do NAME,SIZE,TRAN,MODEL "$real"
  read -r -p "Type the word wipe to continue: " answer
  [ "$answer" = wipe ] || { echo "aborted" >&2; exit 1; }
}
