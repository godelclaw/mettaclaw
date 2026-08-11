import json
base = '/shared/zahrada/krenn/allcollapse_case_artifacts/case_0/'
o = json.load(open(base + 'component_orbits.json'))
missing = [16, 19, 22, 24, 25, 27, 42, 44]
orb = o.get('orbits_1based')
rep = o.get('representatives_1based')
print('orbits_1based type', type(orb).__name__, 'len', len(orb))
print('sample row:', str(orb[0])[:200])
print('reps type', type(rep).__name__, 'len', len(rep))
for i in missing:
    try:
        row = orb[i - 1] if isinstance(orb, list) else orb.get(str(i))
        print('ORBIT', i, str(row)[:250])
    except Exception as e:
        print('ORBIT', i, 'ERR', e)
