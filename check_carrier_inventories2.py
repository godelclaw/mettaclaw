#!/usr/bin/env python3
# Carrier-split conformance checker v2 — sparse-polynomial aware.
# v1 bug: compared coord NAME strings against sparse term lists; equations are
# [[coeff, exponent-vector], ...] polynomials. v2 checks real structure:
# zero bit -> unit-monomial equation [[1, e_ci]] present; nonzero bit ->
# [[1, e_ci+e_ii], [-1, 0]] present; inv-symbol tail offsets match.
import json, hashlib, glob, os, re, sys

BASE = '/shared/zahrada/krenn/allcollapse_case_artifacts/case_0'
BITS = [[(b >> 2) & 1, (b >> 1) & 1, b & 1] for b in range(8)]
INV_RE = re.compile(r'^branch([0-9]+)_inv_([0-9]+)$')

def sha256_bytes(p):
    h = hashlib.sha256()
    f = open(p, 'rb')
    for chunk in iter(lambda: f.read(1 << 20), b''):
        h.update(chunk)
    f.close()
    return h.hexdigest()

def semantic_hash(so):
    canon = json.dumps({'variables': so['variables'], 'equations': so['equations']}, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(canon).hexdigest()

def pad(ev, n):
    ev = list(ev)
    if len(ev) < n:
        ev = ev + [0] * (n - len(ev))
    return tuple(ev)

def eqkey(eq, n):
    return frozenset((t[0], pad(t[1], n)) for t in eq)

invs = sorted(glob.glob(os.path.join(BASE, '**', 'inventory.json'), recursive=True))
if len(sys.argv) > 1:
    cutoff = float(sys.argv[1])
    invs = [p for p in invs if os.path.getmtime(p) >= cutoff]
ok = 0
failed = []
skipped_general = 0
checked_branches = 0
sem_bad = 0
for ipath in invs:
    d = os.path.dirname(ipath)
    errs = []
    try:
        inv = json.load(open(ipath))
    except Exception as e:
        failed.append((ipath, ['inventory unreadable: %s' % e]))
        continue
    if inv.get('branch_count') != 8:
        errs.append('branch_count=%r' % inv.get('branch_count'))
    coords = inv.get('coordinates', [])
    if len(coords) != 3:
        errs.append('n_coordinates=%d' % len(coords))
    branches = inv.get('branches', [])
    if len(branches) != 8:
        errs.append('branches len=%d' % len(branches))
    for i, br in enumerate(branches):
        if br.get('branch') != i:
            errs.append('branch[%d].branch=%r' % (i, br.get('branch')))
            continue
        if br.get('nonzero_bits') != BITS[i]:
            errs.append('branch %d bits=%r expected %r' % (i, br.get('nonzero_bits'), BITS[i]))
        sf = os.path.join(d, 'branch_%d' % i, 'system.json')
        if not os.path.exists(sf):
            errs.append('branch %d system.json missing' % i)
            continue
        checked_branches += 1
        if sha256_bytes(sf) != br.get('system_file_sha256'):
            errs.append('branch %d byte-hash mismatch' % i)
            continue
        try:
            so = json.load(open(sf))
        except Exception as e:
            errs.append('branch %d system unreadable: %s' % (i, e))
            continue
        if semantic_hash(so) != br.get('system_sha256'):
            sem_bad += 1
            errs.append('branch %d semantic-hash mismatch' % i)
        vars_ = so.get('variables', [])
        n = len(vars_)
        vidx = {}
        for x, v in enumerate(vars_):
            vidx[v] = x
        eqset = set(eqkey(e, n) for e in so.get('equations', []))
        nz = [j for j, b in enumerate(BITS[i]) if b]
        tail = vars_[n - len(nz):] if nz else []
        invidx = {}
        for name, j in zip(tail, nz):
            m = INV_RE.match(name)
            if not m or int(m.group(2)) != j:
                errs.append('branch %d inv tail bad: %r for offset %d' % (i, name, j))
            else:
                invidx[j] = vidx[name]
        det = all((j >= len(coords)) or (coords[j] in vidx) for j in range(min(3, len(coords))))
        if not det:
            skipped_general += 1
            continue
        for j, b in enumerate(BITS[i]):
            if j >= len(coords):
                break
            ci = vidx[coords[j]]
            if b == 0:
                unit = tuple(1 if x == ci else 0 for x in range(n))
                if frozenset([(1, unit)]) not in eqset:
                    errs.append('branch %d zero-bit coord %s unit eq missing' % (i, coords[j]))
            else:
                if j not in invidx:
                    continue
                ii = invidx[j]
                ev2 = tuple((1 if x == ci else 0) + (1 if x == ii else 0) for x in range(n))
                zero = tuple(0 for x in range(n))
                if frozenset([(1, ev2), (-1, zero)]) not in eqset:
                    errs.append('branch %d inverse eq c*inv-1 for %s missing' % (i, coords[j]))
    if errs:
        failed.append((ipath, errs))
    else:
        ok += 1

print('inventories found: %d' % len(invs))
print('conformant: %d' % ok)
print('failed: %d' % len(failed))
print('branch systems checked: %d' % checked_branches)
print('semantic-hash mismatches: %d' % sem_bad)
print('general-poly coords (detailed eq check skipped): %d branches' % skipped_general)
for p, es in failed[:15]:
    print('FAIL %s' % p)
    for e in es[:6]:
        print('   - %s' % e)
sys.exit(1 if failed else 0)