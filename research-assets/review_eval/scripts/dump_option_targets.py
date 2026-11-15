from construct_blind_test_phase2 import OPTION_STRUCTURE_SPECS, load_phase1_sources
sources = load_phase1_sources()
for idx, (rid, _, _, _, _) in enumerate(OPTION_STRUCTURE_SPECS, 1):
    s = sources.get(f'blind-option_structure-{rid}')
    print(f"{idx}. {rid}: {s['options']}")
