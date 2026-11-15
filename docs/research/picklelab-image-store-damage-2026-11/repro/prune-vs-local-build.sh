#!/usr/bin/env bash
# Throwaway dind (containerd image store) to test whether the weekly prune
# (builder prune -f, image prune -f) breaks locally built images.
set -uo pipefail
N=prune-repro
docker rm -f $N >/dev/null 2>&1
docker run -d --privileged --name $N docker:29.6.0-dind >/dev/null
for i in $(seq 30); do docker exec $N docker info >/dev/null 2>&1 && break; sleep 1; done
docker exec $N docker info 2>&1 | grep -E "Server Version|driver-type"
CTR="docker exec $N ctr -a /var/run/docker/containerd/containerd.sock -n moby"
check() { echo "--- check: $1"; $CTR images check 2>&1 | grep -E "error|incomplete|complete" | cut -c1-170 | sort | uniq -c | head -12; }
docker exec $N sh -c 'mkdir -p /b && cd /b && cat > Dockerfile <<D
FROM alpine:3.20
RUN dd if=/dev/urandom of=/a bs=1M count=20
RUN dd if=/dev/urandom of=/b bs=1M count=20
COPY app.txt /app.txt
RUN echo built > /done
D
echo v1 > app.txt'
docker exec $N sh -c 'cd /b && docker build -q -t app:local . >/dev/null'
docker exec $N docker run -d --name live app:local sleep 1000000 >/dev/null
docker exec $N docker system df
check "after build v1"
echo "=== builder prune -f"
docker exec $N docker builder prune -f | tail -2
check "after builder prune"
echo "=== rebuild v2 (retag, v1 dangling)"
docker exec $N sh -c 'cd /b && echo v2 > app.txt && docker build -q -t app:local . >/dev/null'
docker exec $N docker image prune -f | tail -2
docker exec $N docker builder prune -f | tail -2
check "after rebuild + both prunes"
echo "=== restart containerd side: restart dockerd (re-reads layers)"
docker restart $N >/dev/null; for i in $(seq 30); do docker exec $N docker info >/dev/null 2>&1 && break; sleep 1; done
docker exec $N docker start live 2>&1 | tail -2
docker exec $N docker run --rm app:local cat /done 2>&1 | tail -2
check "after restart"
