#!/usr/bin/env bash
# Read-only. Which snapshots have no directory on disk, and which images' layers do they belong to?
# Run as root:  sudo bash /tmp/snap-check.sh   -> /tmp/snap-check.out
exec python3 - <<'PY' > /tmp/snap-check.out 2>&1
import hashlib, json, os, subprocess, datetime
CTR = ["ctr", "-n", "moby"]
BLOBS = "/srv/containerd/io.containerd.content.v1.content/blobs/sha256"
def run(*a):
    return subprocess.run(CTR + list(a), capture_output=True, text=True)
def blob(d):
    p = os.path.join(BLOBS, d.split(":")[1])
    return json.load(open(p)) if os.path.exists(p) else None
print("== date", datetime.datetime.utcnow().isoformat() + "Z")
rows = [l.split() for l in run("snapshots", "ls").stdout.splitlines()[1:] if l.strip()]
keys = {r[0]: (r[1] if len(r) > 2 else "") for r in rows}
missing = {k for k in keys if run("snapshots", "usage", k).returncode != 0}
print(f"== snapshots in metadata: {len(keys)}, dir missing (usage fails): {len(missing)}")
def kind(k):
    return "chain" if k.startswith("sha256:") else "other"
print("   missing by key shape:", {s: sum(1 for k in missing if kind(k) == s) for s in ("chain", "other")})
print("   sample non-chain missing keys:", [k[:70] for k in missing if kind(k) == "other"][:5])
claimed = set()
print("== per image: layers / layers whose snapshot is missing / layers with no snapshot at all / blob problems")
for l in run("images", "ls").stdout.splitlines()[1:]:
    p = l.split()
    if len(p) < 3: continue
    name, dig = p[0], p[2]
    m = blob(dig)
    if m is None:
        print(f"{name}: index/manifest blob MISSING"); continue
    if "manifests" in m:
        cand = [x for x in m["manifests"] if x.get("platform", {}).get("architecture") == "amd64" and x.get("platform", {}).get("os") == "linux"]
        if not cand: print(f"{name}: no linux/amd64 manifest"); continue
        m = blob(cand[0]["digest"])
        if m is None: print(f"{name}: amd64 manifest blob MISSING"); continue
    cfg = blob(m["config"]["digest"])
    if cfg is None: print(f"{name}: config blob MISSING"); continue
    diffs = cfg["rootfs"]["diff_ids"]
    chain, prev, miss, absent = [], None, 0, 0
    for d in diffs:
        prev = d if prev is None else "sha256:" + hashlib.sha256((prev + " " + d).encode()).hexdigest()
        chain.append(prev)
    for c in chain:
        if c not in keys: absent += 1
        elif c in missing: miss += 1; claimed.add(c)
        else: claimed.add(c)
    nb = sum(1 for L in m["layers"] if not os.path.exists(os.path.join(BLOBS, L["digest"].split(":")[1])))
    flag = "  <== DAMAGED" if (miss or absent or nb) else ""
    print(f"{name}: layers={len(chain)} snapshot_dir_missing={miss} no_snapshot={absent} blobs_missing={nb}{flag}")
orphans = [k for k in missing if k not in claimed]
print(f"== missing-dir snapshots not part of any image's chain (buildkit cache, containers, leftovers): {len(orphans)}")
for k in orphans[:15]:
    print("  ", k[:80], "<- parent", (keys[k] or "-")[:30])
print("== containers (moby) and whether their snapshot dir exists")
for l in run("containers", "ls").stdout.splitlines()[1:]:
    p = l.split()
    if p: print("  ", p[0][:16], (p[1] if len(p) > 1 else "")[:50], "snapshot_missing" if p[0] in missing else "ok")
PY
chmod 644 /tmp/snap-check.out 2>/dev/null
echo "wrote /tmp/snap-check.out"
