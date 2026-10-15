from hashlib import sha256
import json
import os
from pathlib import Path


root = Path(os.environ["SRE_ENGINE_ROOT"])
front = root / "modern_ui" / "frontend"
names = ("index.html", "app.js", "styles.css", "interaction-bootstrap.js")
manifest = {
    "release": "0.14.5-runtime-interaction-bootstrap",
    "files": {name: sha256((front / name).read_bytes()).hexdigest() for name in names},
}
(root / "release-frontend-manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(manifest, sort_keys=True))
