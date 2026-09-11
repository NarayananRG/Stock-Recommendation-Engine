@echo off
set "PYTHONPATH=%~dp0\.."
python -m stage4a3.ledger_cli --repo-root "%~dp0\..\.."
