import json, hashlib

def sh(p):
    return hashlib.sha256(open(p, 'rb').read()).hexdigest()

base = '/shared/zahrada/krenn/allcollapse_case_artifacts/case_0/'
print('current generator sha:', sh('/shared/zahrada/krenn/branch_frozen_coordinates.py')[:16])
inv = json.load(open(base + 'component01_w01_split/inventory.json'))
print('comp01 format:', inv.get('format'))
print('comp01 generator_sha256:', str(inv.get('generator_sha256'))[:16])
print('comp01 source sha:', str(inv.get('source_system_file_sha256'))[:16])
print('comp01 coords:', inv.get('coordinates'))
so = json.load(open(base + 'component01_w01_split/branch_3/system.json'))
print('b3 vars tail:', so['variables'][-3:])
print('b3 eqs tail:', so['equations'][-2:])
so7 = json.load(open(base + 'component01_w01_split/branch_7/system.json'))
print('b7 vars tail:', so7['variables'][-4:])
print('b7 eqs tail:', so7['equations'][-3:])
for p in ['components', 'components_reduced_v2']:
    o = json.load(open(base + p + '/inventory.json'))
    print(p, '| format:', o.get('format'), '| keys:', sorted(o.keys())[:10])