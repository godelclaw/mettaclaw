import json, glob
from collections import Counter
files = sorted(glob.glob('/shared/zahrada/krenn/allcollapse_case_artifacts/case_0/component*_exact_tree_manifest.json'))
print('n_manifests', len(files))
for f in files[:2]:
    d = json.load(open(f))
    lv = d['leaves']
    print('===', f.split('/')[-1], 'leaves', len(lv))
    for r in lv[:6]:
        print(json.dumps(r)[:220])
c = Counter()
q = Counter()
tags = []
for f in files[:6]:
    d = json.load(open(f))
    for r in d['leaves']:
        c[r.get('verdict')] += 1
        q[r.get('q_verdict')] += 1
        tags.append(r.get('tag'))
print('verdict hist (6 manifests):', dict(c))
print('q_verdict hist:', dict(q))
print('sample tags:', tags[:15])
