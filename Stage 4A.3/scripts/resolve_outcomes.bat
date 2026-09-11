@echo off
setlocal
if "%~4"=="" (
  echo Usage: resolve_outcomes.bat REPO_ROOT OBSERVATION_THROUGH MARKET_ROOT MARKET_MANIFEST [--include-random-controls]
  exit /b 2
)
set "REPO_ROOT=%~1"
set "STAGE_ROOT=%REPO_ROOT%\Stage 4A.3"
set "PYTHONPATH=%STAGE_ROOT%"
python -m stage4a3.outcome_runner --repo-root "%REPO_ROOT%" --observation-through "%~2" --market-root "%~3" --market-manifest "%~4" %5
exit /b %ERRORLEVEL%
