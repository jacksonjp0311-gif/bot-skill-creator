#!/usr/bin/env python3
"""Verify release files against their published manifest; no network or code execution."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import sys
root=Path(__file__).resolve().parent.parent
manifest_path=root/'RELEASE-MANIFEST.json'
if not manifest_path.is_file():
    print('Release manifest is absent. It is generated for packaged releases.')
    sys.exit(1)
manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
errors=[]
for name, expected in manifest['files'].items():
    rel=PurePosixPath(name)
    if rel.is_absolute() or '..' in rel.parts or '\\' in name:
        errors.append('Unsafe path: '+name)
        continue
    path=root.joinpath(*rel.parts)
    if not path.is_file() or path.is_symlink():
        errors.append('Missing or symlink: '+name)
    elif hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        errors.append('Changed: '+name)
print(json.dumps({'ok':not errors,'verified_files':len(manifest['files']),'errors':errors},indent=2))
print('Hashes establish consistency with this manifest, not authenticity of the manifest itself.')
sys.exit(1 if errors else 0)
