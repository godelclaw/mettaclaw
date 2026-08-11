import json
base = '/shared/zahrada/krenn/allcollapse_case_artifacts/case_0/'
p = json.load(open(base + 'component_certificate_progress.json'))
print('type:', type(p).__name__)
if isinstance(p, dict):
    ks = list(p.keys())[:8]
    print('keys sample:', ks)
    for k in ks[:3]:
        print('ROW', k, str(p[k])[:160])
elif isinstance(p, list):
    print('len:', len(p))
    print(str(p[:3])[:300])
