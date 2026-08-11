import json
base = '/shared/zahrada/krenn/allcollapse_case_artifacts/case_0/'
o = json.load(open(base + 'component_orbits.json'))
print('all keys:', list(o.keys()))
for k in ('orbits', 'fixed_orbits'):
    v = o.get(k)
    if v is not None:
        print('KEY', k, 'type', type(v).__name__, 'len', len(v))
        print('sample:', str(v[:2] if isinstance(v, list) else list(v.items())[:2])[:300])
