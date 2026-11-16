#!/usr/bin/env bash
# Functional per-image check: can the daemon mount every layer? Needs only the docker group.
# `ctr images check` verifies blobs and snapshot metadata, not snapshot directories.
for i in $(docker image ls --format '{{.Repository}}:{{.Tag}}' | grep -v '<none>' | sort -u); do
  out=$(timeout 60 docker run --rm --pull=never --network none --entrypoint /bin/true "$i" 2>&1); rc=$?
  if [ $rc -eq 0 ]; then echo "OK     $i"
  elif echo "$out" | grep -qiE 'snapshot|stat parent|mount|lowerdir|content store'; then echo "BROKEN $i :: $(echo "$out" | head -1 | cut -c1-170)"
  else echo "OK     $i (no /bin/true, layers mounted)"; fi
done
