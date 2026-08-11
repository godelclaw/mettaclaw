import json, glob
from collections import Counter
files = sorted(glob.glob('/shared/zahrada/krenn/**/component*_tree_manifest.json', recursive=True))
def depth(t): return len(t.split('.'))
tot_rows = 0; tot_q = 0; q_child = 0; q_slots = 0; q_known = 0; q_unknown = 0
skipped = []
dhist = Counter()
for f in files:
    name = f.split('/')[-1]
    d = json.load(open(f))
    if not (d.get('complete') is True or (isinstance(d.get('summary'), dict) and d['summary'].get('complete') is True)):
        skipped.append(name)
        continue
    rows = {r.get('tag'): r.get('verdict') for r in d['leaves']}
    tot_rows += len(rows)
    qf = sorted([t for t,v in rows.items() if v=='q_not_certified'])
    tot_q += len(qf)
    for t in qf: dhist[depth(t)] += 1
    for t in qf:
        for i in range(8):
            q_slots += 1
            child = t + '.' + str(i)
            if child in rows:
                q_known += 1
                if rows[child] == 'q_not_certified': q_child += 1
            else:
                q_unknown += 1
print('complete manifests used', len(files)-len(skipped), 'skipped incomplete', len(skipped), skipped)
print('rows', tot_rows, 'q_not_certified', tot_q, 'depth hist', dict(dhist))
print('child slots', q_slots, 'known', q_known, 'unknown', q_unknown, 'q_children', q_child)
print('conditional q-rate (known only)', (float(q_child)/q_known) if q_known else 'n/a (no measured children)')
print('base q-rate', (float(tot_q)/tot_rows) if tot_rows else 'n/a')
