import json
base = '/shared/zahrada/krenn/allcollapse_case_artifacts/case_0/'
p = json.load(open(base + 'component_certificate_progress.json'))
certs = p['certificates']
got = sorted(set(c['component_orbit_index'] for c in certs))
n_orbits = p['component_orbit_count']
missing = [i for i in range(1, n_orbits + 1) if i not in got]
print('orbit_count', n_orbits)
print('certified_orbit_indices', got)
print('missing_orbit_indices', missing)
print('n_missing', len(missing))
