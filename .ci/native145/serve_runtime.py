from pathlib import Path
import os
import sys

import uvicorn


root = Path(os.environ["SRE_ENGINE_ROOT"]).resolve()
sys.path.insert(0, str(root))

from modern_ui.api import create_app  # noqa: E402


app_data = Path(os.environ["SRE_BROWSER_APP_DATA"]).resolve()
app = create_app(repo_root=root, app_data_dir=app_data)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ["SRE_BROWSER_PORT"]), log_level="warning")
