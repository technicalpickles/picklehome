#!/usr/bin/env bash
# Read-only inventory of the rootless ci dockerd and /srv/ci-docker. Run as root:
#   sudo bash /tmp/ci-docker-check.sh   -> writes /tmp/ci-docker-check.out
OUT=/tmp/ci-docker-check.out
CI_UID=2000
as_ci() { sudo -iu ci "$@" 2>&1; }
{
echo "== date: $(date -u +%FT%TZ)"
echo "== mount"; findmnt -no SOURCE,TARGET,FSTYPE,OPTIONS /srv/ci-docker; df -h /srv/ci-docker | tail -1
echo "== top level of /srv/ci-docker"; ls -la /srv/ci-docker
echo "== du by dir (one level, same fs)"; du -xh --max-depth=2 /srv/ci-docker 2>/dev/null | sort -h | tail -15
echo "== user@$CI_UID unit and drop-ins"; systemctl is-active user@$CI_UID; systemctl cat user@$CI_UID.service 2>&1 | grep -E "^# /etc|RequiresMountsFor"
echo "== ci user docker units"; as_ci env XDG_RUNTIME_DIR=/run/user/$CI_UID systemctl --user list-units --no-pager 'docker*' 'containerd*'
echo "== ci daemon.json"; cat /home/ci/.config/docker/daemon.json 2>&1
echo "== ci systemd user overrides"; ls -R /home/ci/.config/systemd/user 2>&1 | head -20
echo "== processes"; ps -eo pid,user,lstart,args | grep -E "dockerd|containerd" | grep -E "^ *[0-9]+ +(ci|2000)" | grep -v grep | cut -c1-220
echo "== docker info (ci)"; as_ci docker info --format 'root={{.DockerRootDir}} driver={{.Driver}} {{.DriverStatus}} ver={{.ServerVersion}} containers={{.Containers}} images={{.Images}}'
echo "== docker system df (ci)"; as_ci docker system df
echo "== images (ci)"; as_ci docker image ls --format '{{.Repository}}:{{.Tag}}  {{.Size}}  {{.CreatedSince}}'
echo "== containers (ci)"; as_ci docker ps -a --format '{{.Names}}  {{.Image}}  {{.Status}}'
echo "== volumes (ci), reclaimable ones"; as_ci docker volume ls -q | wc -l
echo "== rootless containerd socket + images check"
SOCK=$(ls /run/user/$CI_UID/docker/containerd/containerd.sock /run/user/$CI_UID/containerd/containerd.sock 2>/dev/null | head -1)
echo "socket=$SOCK"
if [ -n "$SOCK" ]; then
  as_ci ctr -a "$SOCK" namespaces ls
  as_ci ctr -a "$SOCK" -n moby images check 2>&1 | grep -E "error|incomplete" | cut -c1-200
  as_ci ctr -a "$SOCK" -n moby content ls -q | wc -l
  as_ci ctr -a "$SOCK" -n moby snapshots ls | wc -l
fi
echo "== content blobs and snapshot dirs on disk"
find /srv/ci-docker -type d -path '*io.containerd.content.v1.content/blobs/sha256' 2>/dev/null | while read -r d; do echo "$d: $(ls "$d" | wc -l)"; done
find /srv/ci-docker -maxdepth 6 -type d -path '*overlayfs/snapshots' 2>/dev/null | while read -r d; do echo "$d: $(ls "$d" | wc -l)"; done
echo "== woodpecker agent and runner state"
docker ps --format '{{.Names}}  {{.Image}}  {{.Status}}' 2>&1 | grep -iE "woodpecker|runner|agent"
echo "== leftovers"; ls -d /srv/ci-docker*.old /srv/ci-docker/*.old 2>&1 | head -3
echo "== newest/oldest mtimes under ci-docker (depth 2)"
find /srv/ci-docker -maxdepth 2 -printf '%TY-%Tm-%Td %TH:%TM  %p\n' 2>/dev/null | sort | sed -n '1,3p;$p'
echo "== kernel log, ci-docker device"; dmesg 2>/dev/null | grep -iE "ci--docker|dm-3|EXT4-fs.*error" | tail -5
} > "$OUT" 2>&1
chmod 644 "$OUT"
echo "wrote $OUT"
