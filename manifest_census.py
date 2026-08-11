import json, glob
fs = sorted(glob.glob('/shared/zahrada/krenn/**/component*_tree_manifest.json', recursive=True))
done = 0
incomp = []
for f in fs:
    s = json.load(open(f)).get('summary', {})
    if s.get('complete') is True:
        done += 1
    else:
        incomp.append(f.split('/')[-1])
print('total', len(fs), 'complete', done)
print('incomplete:', incomp)
