#!/usr/bin/env bash
# Dry-run by default. Finds the committed snapshot that is the PARENT of the layer a pull cannot extract
# (its directory is gone on disk but containerd still has a record), then with --apply removes that record
# (children first) so the pull can re-extract it. Only touches snapshot RECORDS whose directory is missing.
#   sudo bash /tmp/fix-dangling-parent.sh            # report only  -> /tmp/fix-dangling-parent.out
#   sudo bash /tmp/fix-dangling-parent.sh --apply    # remove records
TARGET_CHAIN="${TARGET_CHAIN:-sha256:5e3b366e43c52214085e578e0f13405f8ae6325a82d3b15c3e4ebae924647930}"
export TARGET_CHAIN APPLY="${1:-}"
exec python3 - <<'PY' > /tmp/fix-dangling-parent.out 2>&1
import hashlib, json, os, subprocess
T, APPLY = os.environ["TARGET_CHAIN"], os.environ.get("APPLY") == "--apply"
BLOBS = "/srv/containerd/io.containerd.content.v1.content/blobs/sha256"
SNAPDIR = "/srv/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots"
ctr = lambda *a: subprocess.run(["ctr", "-n", "moby", *a], capture_output=True, text=True)
rows = [l.split() for l in ctr("snapshots", "ls").stdout.splitlines()[1:] if l.strip()]
parent_of = {r[0]: (r[1] if len(r) > 2 else "") for r in rows}
chain_of_parent = None
for f in os.listdir(BLOBS):
    p = os.path.join(BLOBS, f)
    if os.path.getsize(p) > 300000: continue
    try: o = json.load(open(p))
    except Exception: continue
    ids = o.get("rootfs", {}).get("diff_ids") if isinstance(o, dict) else None
    if not ids: continue
    chains, prev = [], None
    for d in ids:
        prev = d if prev is None else "sha256:" + hashlib.sha256((prev + " " + d).encode()).hexdigest()
        chains.append(prev)
    if T in chains:
        i = chains.index(T)
        print(f"config blob {f[:12]}: target layer index {i} of {len(chains)}")
        if i > 0: chain_of_parent = chains[i - 1]; break
print("target chain:", T[:20], "parent chain:", (chain_of_parent or "none")[:20])
if not chain_of_parent: raise SystemExit("could not find the config that owns the target layer")
print("parent record in containerd:", chain_of_parent in parent_of)
def descendants(k):
    out = []
    for c in [c for c, p in parent_of.items() if p == k]:
        out += descendants(c) + [c]
    return out
tree = descendants(chain_of_parent) if chain_of_parent in parent_of else []
print("descendants (deepest first):", len(tree))
for d in tree: print("   ", d[:40], "<- parent", parent_of[d][:20])
import re
containers = [d for d in tree if re.fullmatch(r"[0-9a-f]{64}", d)]
if containers:
    raise SystemExit(f"ABORT: descendants look like container snapshots (64 hex): {containers[:5]}")
print("non-chain descendants (buildkit-style keys, all rest on the broken parent):", len([d for d in tree if not d.startswith("sha256:")]))
victims = tree + ([chain_of_parent] if chain_of_parent in parent_of else [])
print("would remove (deepest first):", len(victims), "records")
if APPLY:
    for v in victims:
        r = ctr("snapshots", "rm", v); print("rm", v[:30], "rc", r.returncode, r.stderr.strip()[:120])
else:
    print("dry run; rerun with --apply to remove")
PY
chmod 644 /tmp/fix-dangling-parent.out
echo "wrote /tmp/fix-dangling-parent.out"
