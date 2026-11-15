#!/usr/bin/env bash
# Read-only whole-store audit of containerd's moby namespace. Tests whether the damage is a closed,
# unreferenced set (a GC-able leftover) or spread through records live images and containers use.
# Run as root:  sudo bash /tmp/store-audit.sh   -> /tmp/store-audit.out
exec python3 - <<'PY' > /tmp/store-audit.out 2>&1
import collections, datetime, hashlib, json, os, subprocess
ROOT = "/srv/containerd"
BLOBS = f"{ROOT}/io.containerd.content.v1.content/blobs/sha256"
SNAPDIR = f"{ROOT}/io.containerd.snapshotter.v1.overlayfs/snapshots"
def ctr(*a, ns="moby"):
    return subprocess.run(["ctr", "-n", ns, *a], capture_output=True, text=True).stdout.splitlines()
def has_blob(d): return os.path.exists(os.path.join(BLOBS, d.split(":")[1]))
def blob(d):
    p = os.path.join(BLOBS, d.split(":")[1])
    return json.load(open(p)) if os.path.exists(p) else None
print("== date", datetime.datetime.utcnow().isoformat() + "Z")

# content
content = {}
for l in ctr("content", "ls")[1:]:
    p = l.split(None, 3)
    if p: content[p[0]] = p[3] if len(p) > 3 else ""
no_file = {d for d in content if not has_blob(d)}
print(f"== content records={len(content)} record_without_file={len(no_file)}")
src = collections.Counter()
for d in no_file:
    s = [x for x in content[d].split(",") if "distribution.source" in x]
    src[s[0].split("=", 1)[1] if s else "(no source label: built locally)"] += 1
for k, v in src.most_common(): print(f"   {v:4d}  {k}")
all_meta = set()
for ns in [l.strip() for l in ctr("namespaces", "ls", "-q", ns="default")]:
    all_meta |= {l.strip() for l in ctr("content", "ls", "-q", ns=ns)}
disk = {"sha256:" + f for f in os.listdir(BLOBS)}
print(f"== blob files on disk={len(disk)} with no record in any namespace={len(disk - all_meta)}")

# snapshots
snaps = {}
for l in ctr("snapshots", "ls")[1:]:
    p = l.split()
    if p: snaps[p[0]] = (p[1] if len(p) == 3 else "", p[-1])
nodir = {k for k in snaps if subprocess.run(["ctr", "-n", "moby", "snapshots", "usage", k], capture_output=True).returncode != 0}
print(f"== snapshots={len(snaps)} kinds={dict(collections.Counter(v[1] for v in snaps.values()))} record_without_dir={len(nodir)}")
bad_parent = {k for k, (par, _) in snaps.items() if par and (par not in snaps or par in nodir)}
print(f"   snapshots whose parent is missing or dir-less: {len(bad_parent)}")
for k in sorted(bad_parent)[:10]: print("     ", k[:40], "<-", snaps[k][0][:40])

# what live things depend on
img_chain, img_blobs, damaged_imgs = set(), set(), []
for l in ctr("images", "ls")[1:]:
    p = l.split()
    if len(p) < 3: continue
    name, dig = p[0], p[2]
    img_blobs.add(dig); m = blob(dig)
    if m and "manifests" in m:
        c = [x for x in m["manifests"] if x.get("platform", {}).get("architecture") == "amd64"]
        if c: img_blobs.add(c[0]["digest"]); m = blob(c[0]["digest"])
    if not m or "config" not in m: damaged_imgs.append(name + " (manifest)"); continue
    img_blobs.add(m["config"]["digest"]); img_blobs |= {L["digest"] for L in m["layers"]}
    cfg = blob(m["config"]["digest"])
    if not cfg: damaged_imgs.append(name + " (config)"); continue
    prev = None
    for d in cfg["rootfs"]["diff_ids"]:
        prev = d if prev is None else "sha256:" + hashlib.sha256((prev + " " + d).encode()).hexdigest()
        img_chain.add(prev)
ctr_snaps = {l.split()[0] for l in ctr("containers", "ls")[1:] if l.split()}
live_snaps = set(img_chain)
for k in list(ctr_snaps):
    while k in snaps and k not in live_snaps:
        live_snaps.add(k); k = snaps[k][0]
print(f"== images={len([l for l in ctr('images','ls')[1:] if l.strip()])} damaged={damaged_imgs}")
print(f"   live-referenced blobs missing a file: {len(img_blobs & no_file)}")
print(f"   live-referenced snapshots (image chains + container ancestry) missing dir or record: "
      f"{len({k for k in live_snaps if k not in snaps or k in nodir})}")
print(f"== damage outside anything live: content={len(no_file - img_blobs)} snapshots={len(nodir - live_snaps)}")
print(f"   snapshots not referenced by any image or container (GC candidates once unleased): {len(set(snaps) - live_snaps)}")

# leases: what pins the leftovers
leases = [l for l in ctr("leases", "ls")[1:] if l.strip()]
print(f"== leases={len(leases)}")
pref = collections.Counter()
for l in leases:
    i = l.split()[0]
    pref[i.split("-")[0][:12] if "-" in i else ("hex" if all(c in "0123456789abcdef" for c in i) else i[:12])] += 1
print("   by id prefix:", pref.most_common(8))
ages = sorted(l.split()[1] for l in leases if len(l.split()) > 1)
if ages: print("   oldest:", ages[0], "newest:", ages[-1])
expiring = sum(1 for l in leases if "containerd.io/gc.expire" in l)
print(f"   with gc.expire label: {expiring}")
print("   sample:"); [print("     ", l[:160]) for l in leases[:6]]

# the moby_history namespace
h = [l for l in ctr("content", "ls", ns="moby_history")[1:] if l.strip()]
print(f"== moby_history content={len(h)} sample labels:"); [print("     ", l[:160]) for l in h[:3]]
print("== disk usage"); os.system(f"du -sh {BLOBS} {SNAPDIR} {ROOT}/io.containerd.metadata.v1.bolt 2>&1")
PY
chmod 644 /tmp/store-audit.out
echo "wrote /tmp/store-audit.out"
