import json
p=json.load(open('/shared/zahrada/krenn/allcollapse_case_artifacts/case_0/component_certificate_progress.json'))
print('top keys:', sorted(p.keys()))
certs=p.get('certificates',[])
print('orbits certified:', len(certs))
if certs:
    print('cert keys:', sorted(certs[0].keys()))
    tot=sum(c.get('strict_leaf_count',0) for c in certs)
    print('total strict leaves:', tot)
    kinds={}
    for c in certs:
        k=c.get('runner_kind')
        kinds[k]=kinds.get(k,0)+1
    print('runner kinds:', kinds)
    print('orbit reps:', sorted(c.get('representative_component',-1) for c in certs))
cc=p.get('component_count')
print('component_count:', cc, 'orbit_count:', p.get('component_orbit_count'))
print('covered via symmetry:', p.get('certified_component_count_via_symmetry'))
covl=p.get('covered_components_1based')
if covl and cc:
    print('uncovered components:', sorted(set(range(1,cc+1))-set(covl)))
