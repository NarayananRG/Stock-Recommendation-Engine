from pathlib import Path
import base64
import gzip

here = Path(__file__).resolve().parent
payload = (here / "patch105_integration.py.gz.b64").read_text(encoding="ascii").strip()
source = gzip.decompress(base64.b64decode(payload)).decode("utf-8")
compiled = compile(source, str(here / "patch105_integration.py"), "exec")
exec(compiled, {"__name__": "__main__", "__file__": str(here / "patch105_integration.py")})
