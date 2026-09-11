@echo off
set "PYTHONPATH=%~dp0\.."
python -m stage4a3.prospective_runner --repo-root "%~dp0\..\.."
