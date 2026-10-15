from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import sys
from zipfile import ZipFile


archive = Path(sys.argv[1])
with ZipFile(archive) as bundle:
    members = {PurePosixPath(name.replace("\\", "/")): name for name in bundle.namelist()}

    def read(suffix: str) -> bytes:
        matches = [raw for path, raw in members.items() if str(path).endswith(suffix)]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one {suffix!r} in package, found {matches}")
        return bundle.read(matches[0])

    manifest = json.loads(read("release-frontend-manifest.json"))
    for name, expected in manifest["files"].items():
        actual = sha256(read(f"modern_ui/frontend/{name}")).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Packaged frontend mismatch for {name}: {actual} != {expected}")

print("PACKAGED FRONTEND MANIFEST PASS")
