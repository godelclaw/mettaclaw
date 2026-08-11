import json
base = '/shared/zahrada/krenn/allcollapse_case_artifacts/case_0/'
o = json.load(open(base + 'component_orbits.json'))
print('type:', type(o).__name__)
if isinstance(o, dict):
    print('keys sample:', list(o.keys())[:6])
missing = [16, 19, 22, 24, 25, 27, 42, 44]
if isinstance(o, list):
    for i in missing:
        if i - 1 < len(o):
            print('orbit', i, str(o[i-1])[:200])
elif isinstance(o, dict):
    for i in missing:
        for k in (str(i), i):
            if k in o:
                print('orbit', i, str(o[k])[:200])
