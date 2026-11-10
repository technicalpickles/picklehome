#!/usr/bin/env bash
# Move /srv/containerd and /srv/ci-docker onto their own LVs.
# Run on picklelab, as root. Runbook: docs/plans/2026-10-16-picklelab-disk-swap.md ("Docker split").
#
#   docker-split.sh seed      create + fill the LVs while everything runs (rerunnable)
#   docker-split.sh cutover   short Docker downtime: final copy, swap in the mounts, restart
#   docker-split.sh resume    start what cutover stopped (also the way back before the mv)
#   docker-split.sh verify    read-only status
#   docker-split.sh cleanup   delete the pre-split copies, a day after cutover
set -Eeuo pipefail

VG=vg0
LVS=(containerd:150G ci-docker:30G)
TIMERS=(backup.timer docker-prune.timer nikke-sync.timer climate-auto-switch.timer)
STATE=/var/lib/docker-split
MIN_CLEANUP_AGE_S=72000
STOPPED=0

die() { echo "ERROR: $*" >&2; exit 1; }
say() { echo "==> $*"; }
names() { local e; for e in "${LVS[@]}"; do echo "${e%%:*}"; done; }
size_of() {
  local e
  for e in "${LVS[@]}"; do
    if [ "${e%%:*}" = "$1" ]; then echo "${e##*:}"; return 0; fi
  done
  die "unknown LV $1"
}

on_exit() {
  local rc=$?
  if [ "$rc" -ne 0 ] && [ "$STOPPED" -eq 1 ]; then
    echo "FAILED with Docker stopped. Before the mv: $0 resume. After it: fix by hand, see the runbook." >&2
  fi
}
trap on_exit EXIT

need_root() { [ "$(id -u)" -eq 0 ] || die "run as root (sudo $0 $*)"; }

by_id() {
  local real id
  real=$(readlink -f "/dev/$VG/$1")
  for id in /dev/disk/by-id/dm-uuid-LVM-*; do
    [ "$(readlink -f "$id")" = "$real" ] && { echo "$id"; return; }
  done
  die "no dm-uuid-LVM by-id link for $VG/$1"
}

cut_over() { mountpoint -q "/srv/$1"; }

seed_one() {
  local name=$1 size dev fstype
  size=$(size_of "$name")
  dev=/dev/$VG/$name
  cut_over "$name" && die "/srv/$name is already a mountpoint, nothing to seed"

  if ! lvs "$VG/$name" >/dev/null 2>&1; then
    say "lvcreate $name ($size)"
    lvcreate -L "$size" -n "$name" "$VG"
  fi

  fstype=$(blkid -o value -s TYPE "$dev" || true)
  if [ -z "$fstype" ]; then
    say "mkfs.ext4 $dev"
    mkfs.ext4 -q -m 1 -L "$name" "$dev"
  elif [ "$fstype" != ext4 ]; then
    die "$dev already holds a $fstype filesystem, refusing to touch it"
  fi

  mkdir -p "/mnt/$name"
  mountpoint -q "/mnt/$name" || mount "$dev" "/mnt/$name"

  say "rsync /srv/$name -> /mnt/$name (live, inconsistent is fine, cutover fixes it)"
  rsync -aHAX --numeric-ids --info=stats1 "/srv/$name/" "/mnt/$name/"
}

seed() {
  local name free
  free=$(vgs --noheadings --nosuffix --units g -o vg_free "$VG" | tr -d ' ' | cut -d. -f1)
  [ "$free" -ge 200 ] || die "only ${free}G free in $VG, need ~180G"
  for name in $(names); do seed_one "$name"; done
  say "seeded. df:"
  df -h /mnt/containerd /mnt/ci-docker
  echo "Next: pick a quiet moment, 'just openclaw-quiet' on the Mac, then: $0 cutover"
}

active_timers() {
  local t
  for t in "${TIMERS[@]}"; do systemctl is-active --quiet "$t" && echo "$t"; done
  return 0
}

docker_dependents() {
  local u
  for u in $(systemctl show -p RequiredBy --value docker.service); do
    systemctl is-active --quiet "$u" && echo "$u"
  done
  return 0
}

stat_pair() { stat -c '%U:%G %a' "/srv/$1" "/srv/$1.old" | uniq | wc -l; }

resume() {
  local u t
  say "starting containerd, docker, ci user manager"
  systemctl start containerd docker.socket docker
  systemctl start user@2000.service
  if [ -f "$STATE/units" ]; then
    while read -r u; do [ -n "$u" ] && { say "start $u"; systemctl start "$u"; }; done <"$STATE/units"
  fi
  if [ -f "$STATE/timers" ]; then
    while read -r t; do [ -n "$t" ] && systemctl start "$t"; done <"$STATE/timers"
  fi
  verify
}

cutover() {
  local name id t answer
  mkdir -p "$STATE"
  for name in $(names); do
    cut_over "$name" && die "/srv/$name is already a mountpoint"
    mountpoint -q "/mnt/$name" || die "/mnt/$name not mounted, run seed first"
    [ "$(blkid -o value -s TYPE "/dev/$VG/$name")" = ext4 ] || die "$VG/$name is not ext4"
  done
  systemctl is-active --quiet backup.service && die "backup.service is running, wait for it"

  active_timers >"$STATE/timers"
  docker_dependents >"$STATE/units"
  docker ps -q | wc -l >"$STATE/container-count"
  say "will restart $(wc -l <"$STATE/units") units and $(wc -l <"$STATE/timers") timers afterwards"
  read -r -p "Docker goes down now. Type the word split to continue: " answer
  [ "$answer" = split ] || die "aborted, nothing changed"

  say "stopping timers, docker, containerd, ci user manager"
  STOPPED=1
  while read -r t; do [ -n "$t" ] && systemctl stop "$t"; done <"$STATE/timers"
  systemctl stop docker.socket docker containerd
  systemctl stop user@2000.service

  if pgrep -x containerd >/dev/null || pgrep -x dockerd >/dev/null || pgrep -u ci >/dev/null; then
    pgrep -a -x containerd || true; pgrep -a -x dockerd || true; pgrep -u ci -a || true
    die "something still runs against the data dirs, stop it and rerun cutover"
  fi

  for name in $(names); do
    say "final copy $name (--delete)"
    rsync -aHAX --numeric-ids --delete --exclude=/lost+found "/srv/$name/" "/mnt/$name/"
  done

  [ -f /etc/fstab.pre-docker-split ] || cp -p /etc/fstab /etc/fstab.pre-docker-split
  for name in $(names); do
    umount "/mnt/$name"
    mv "/srv/$name" "/srv/$name.old"
    mkdir "/srv/$name"
    chattr +i "/srv/$name"
    id=$(by_id "$name")
    grep -q " /srv/$name " /etc/fstab || echo "$id /srv/$name ext4 defaults 0 2" >>/etc/fstab
  done

  mkdir -p /etc/systemd/system/containerd.service.d /etc/systemd/system/docker.service.d /etc/systemd/system/user@2000.service.d
  printf '[Unit]\nRequiresMountsFor=/srv/containerd\n' >/etc/systemd/system/containerd.service.d/10-requires-mount.conf
  printf '[Unit]\nRequiresMountsFor=/srv/containerd\n' >/etc/systemd/system/docker.service.d/10-requires-mount.conf
  printf '[Unit]\nRequiresMountsFor=/srv/ci-docker\n' >/etc/systemd/system/user@2000.service.d/10-requires-mount.conf
  systemctl daemon-reload
  mount -a
  for name in $(names); do cut_over "$name" || die "/srv/$name did not mount"; done

  for name in $(names); do
    [ "$(stat_pair "$name")" -eq 1 ] || { stat -c '%n %U:%G %a' "/srv/$name" "/srv/$name.old"; die "owner or mode of /srv/$name differs from /srv/$name.old, fix before starting anything"; }
  done

  STOPPED=0
  date +%s >"$STATE/cutover-at"
  resume
  echo "Next: run a CI build to prove the rootless daemon, compare containers (was $(cat "$STATE/container-count")), then a day later: $0 cleanup"
}

verify() {
  local name
  findmnt /srv/containerd /srv/ci-docker || true
  for name in $(names); do stat -c '%n %U:%G %a' "/srv/$name"; done
  echo "containers: $(docker ps -q | wc -l) (before cutover: $(cat "$STATE/container-count" 2>/dev/null || echo unknown))"
  systemctl --failed --no-legend
  df -h /srv /srv/containerd /srv/ci-docker 2>/dev/null || true
}

cleanup() {
  local name age answer
  [ -f "$STATE/cutover-at" ] || die "no cutover recorded"
  age=$(( $(date +%s) - $(cat "$STATE/cutover-at") ))
  [ "$age" -ge "$MIN_CLEANUP_AGE_S" ] || die "cutover was $((age / 3600))h ago, wait until it has run a day"
  for name in $(names); do cut_over "$name" || die "/srv/$name is not mounted, refusing to delete its .old"; done
  read -r -p "Delete /srv/containerd.old and /srv/ci-docker.old for good. Type the word delete: " answer
  [ "$answer" = delete ] || die "aborted"
  for name in $(names); do rm -rf "/srv/$name.old"; done
  df -h /srv
}

need_root "$@"
case "${1:-}" in
  seed) seed ;;
  cutover) cutover ;;
  resume) resume ;;
  verify) verify ;;
  cleanup) cleanup ;;
  *) sed -n '2,10p' "$0"; exit 2 ;;
esac
