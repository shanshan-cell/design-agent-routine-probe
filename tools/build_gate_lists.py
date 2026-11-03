#!/usr/bin/env python3
# Builds gate/v0-pre-gate.json from a saved copy of V0's project/design-system.json.
#   python3 -I tools/build_gate_lists.py <design-system.json> <v0 version> > gate/v0-pre-gate.json
#
# Before the exploration gate opens, the guard lets a run read only the V0 files the skill's Step 1-2 needs (brand
# foundations, page model, intent and journey, claims) and only the production media assets. Everything that shows
# previous designs, patterns, examples or review verdicts opens after the run's page narratives exist.
import json
import sys

# V0 files readable before the gate (exact paths). 13, 14, 15, 16, 20, 23, 24, 25, 26, 29, ROADMAP, archived/,
# layout-library/, components/ and the history asset groups are not: they hold composed forms, calibrated scores,
# past runs and verdicts (26 §3b-3c, 29 §1-4, 13 production compositions, 23 examples).
PRE_GATE_FILES = [
    'SKILL.md',
    'index.html',
    'project/00-generation-contract.md',
    'project/01-scope-and-status.md',
    'project/02-visual-foundations.md',
    'project/03-responsive-and-platform.md',
    'project/04-data-contract.md',
    'project/07-sources.md',
    'project/10-experiment-slots.md',
    'project/11-terminology-and-claims.md',
    'project/21-page-model-and-glossary.md',
    'project/22-intent-and-experiment-reasoning.md',
    'project/27-goal-journey-intent.md',
    'project/DECISIONS.md',
    'project/README.md',
    'project/tokens.json',
    'project/design-system.json',
]
# Asset groups that are production media (approved for use), not history or evidence.
PRE_GATE_GROUPS = [
    'Icons', 'Production UI Icons', 'Production Marketing Art', 'Game Page Art', 'Locale Flags', 'Catalog Thumbnails',
    'Brand & Icons', 'Production Fonts', 'Logos', 'Product Assets', 'Figma Feature Icons',
]

src, version = sys.argv[1], sys.argv[2]
ds = json.load(open(src))
groups = ds['assetGroups']
assets = {}
for g in PRE_GATE_GROUPS:
    for name, f in groups[g]['files'].items():
        assets[f['blob']] = f'{g}/{name}'
files = PRE_GATE_FILES + [f'project/assets/{g}/README.md' for g in PRE_GATE_GROUPS]
json.dump({
    'v0_version': version,
    'pre_gate_files': sorted(files),
    'pre_gate_assets': dict(sorted(assets.items())),
    'gated_groups': sorted(set(groups) - set(PRE_GATE_GROUPS)),
}, sys.stdout, indent=1)
print()
