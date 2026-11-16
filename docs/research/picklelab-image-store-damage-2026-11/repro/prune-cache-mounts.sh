#!/usr/bin/env bash
set -uo pipefail
N=prune-repro
CTR="docker exec $N ctr -a /var/run/docker/containerd/containerd.sock -n moby"
check() { echo "--- check: $1"; $CTR images check 2>&1 | awk '{print $NF, $(NF-1), $(NF-2)}' | cut -c1-80; $CTR content ls -q 2>/dev/null | wc -l; }
docker exec $N sh -c 'mkdir -p /c && cd /c && cat > Dockerfile <<D
FROM alpine:3.20 AS base
RUN dd if=/dev/urandom of=/base bs=1M count=15
FROM base
ARG N=0
RUN --mount=type=cache,target=/cache dd if=/dev/urandom of=/cache/c\$N bs=1M count=30 && echo \$N > /n
RUN dd if=/dev/urandom of=/l\$N bs=1M count=10
D'
for n in 1 2 3 4 5 6; do docker exec $N sh -c "cd /c && docker build -q --build-arg N=$n -t svc$n:local . >/dev/null"; done
for n in 1 2 3; do docker exec $N sh -c "cd /c && docker build -q --build-arg N=$n --build-arg X=$RANDOM -t svc$n:local . >/dev/null"; done
docker exec $N docker system df | grep -E "Images|Build"
check "before"
docker exec $N docker builder prune -f | tail -1
docker exec $N docker image prune -f | tail -1
docker exec $N docker system df | grep -E "Images|Build"
check "after prune"
docker restart $N >/dev/null; for i in $(seq 30); do docker exec $N docker info >/dev/null 2>&1 && break; sleep 1; done
for n in 1 2 3 4 5 6; do docker exec $N docker run --rm svc$n:local cat /n 2>&1 | tail -1; done
check "after restart"
