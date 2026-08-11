import json, glob
from collections import Counter, defaultdict
files = sorted(glob.glob('/shared/zahrada/krenn/**/component*_tree_manifest.json', recursive=True))
print('n_manifests', len(files))
for f in files:
    print('M', f)
print('---VERDICTS-ALL---')
vh = Counter()
rows = []
for f in files:
    d = json.load(open(f))
    for r in d['leaves']:
        v = r.get('verdict')
        vh[v] += 1
        rows.append((f.split('/')[-1], r.get('tag'), v))
print(dict(vh))
print('---NON-CONFORMANT ROWS---')
for fn, tag, v in rows:
    if v != 'strict_exact_identity':
        print(fn, tag, v)
