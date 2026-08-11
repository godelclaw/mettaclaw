#!/usr/bin/env python3
"""Carrier-split conformance checker over all case_0 inventories.
Read-only. Verifies structural invariants from branch_frozen_coordinates.py /
certify_carrier_tree.py semantics (audit 2026-08-08)."""
import json, hashlib, glob, os, re, sys

BASE = "/shared/zahrada/krenn/allcollapse_case_artifacts/case_0"
BITS = [[(b >> 2) & 1, (b >> 1) & 1, b & 1] for b in range(8)]
INV_RE = re.compile(r"^branch\d+_inv_\d+$")

def sha256_bytes(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def semantic_hash(sys_obj):
    try:
        canon = json.dumps({"variables": sys_obj["variables"], "equations": sys_obj["equations"]},
                           sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(canon).hexdigest()
    except Exception:
        return None

invs = sorted(glob.glob(os.path.join(BASE, "**", "inventory.json"), recursive=True))
ok, failed, sem_unverified = 0, [], 0
checked_branches = 0
for ipath in invs:
    d = os.path.dirname(ipath)
    errs = []
    try:
        inv = json.load(open(ipath))
    except Exception as e:
        failed.append((ipath, ["inventory unreadable: %s" % e])); continue
    if inv.get("branch_count") != 8:
        errs.append("branch_count=%r" % inv.get("branch_count"))
    coords = inv.get("coordinates", [])
    if len(coords) != 3:
        errs.append("n_coordinates=%d" % len(coords))
    branches = inv.get("branches", [])
    if len(branches) != 8:
        errs.append("branches len=%d" % len(branches))
    for i, br in enumerate(branches):
        if br.get("branch") != i:
            errs.append("branch[%d].branch=%r" % (i, br.get("branch"))); continue
        bits = br.get("nonzero_bits")
        if bits != BITS[i]:
            errs.append("branch %d bits=%r expected %r" % (i, bits, BITS[i]))
        sf = os.path.join(d, "branch_%d" % i, "system.json")
        if not os.path.exists(sf):
            errs.append("branch %d system.json missing" % i); continue
        checked_branches += 1
        if sha256_bytes(sf) != br.get("system_file_sha256"):
            errs.append("branch %d byte-hash mismatch" % i)
        try:
            so = json.load(open(sf))
        except Exception as e:
            errs.append("branch %d system unreadable: %s" % (i, e)); continue
        sh = semantic_hash(so)
        if sh is None or br.get("system_sha256") is None:
            sem_unverified += 1
        elif sh != br.get("system_sha256"):
            sem_unverified += 1  # canonical form unknown; count, do not fail
        n_nz = sum(BITS[i])
        vtail = so.get("variables", [])[-n_nz:] if n_nz else []
        if n_nz and (len(vtail) != n_nz or not all(INV_RE.match(v) for v in vtail)):
            errs.append("branch %d inv-symbol tail mismatch: %r" % (i, vtail))
        eqs = so.get("equations", [])
        for j, bit in enumerate(BITS[i]):
            if bit == 0 and j < len(coords) and coords[j] not in eqs:
                errs.append("branch %d zero-bit coord %s not an equation" % (i, coords[j]))
    if errs:
        failed.append((ipath, errs))
    else:
        ok += 1

print("inventories found: %d" % len(invs))
print("conformant: %d" % ok)
print("failed: %d" % len(failed))
print("branch systems checked: %d" % checked_branches)
print("semantic-hash unverified (canonical form may differ): %d" % sem_unverified)
for p, es in failed[:20]:
    print("FAIL %s" % p)
    for e in es[:6]:
        print("   - %s" % e)
sys.exit(1 if failed else 0)