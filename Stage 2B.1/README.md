# Stage 2B.1 — reproducibility and research audit

Stage 2B.1 finalizes the reporting, portability, hashing, validation, and diagnostics around the accepted Stage 2B daily trade-management engine. It does not change Stage 2.1 signals, Stage 2.2.2 Final entries, or accepted Stage 2B D1–D6 behavior.

## Repository layout

The normal layout is repository-relative:

```text
Stock-Recommendation-Engine/
  Stage 2.2.2 Final/
  Stage 2B/
  Stage 2B.1/
```

The runner resolves only `REPO_ROOT / "Stage 2.2.2 Final"` and `REPO_ROOT / "Stage 2B"`. It does not search arbitrary parent directories. Controlled local tests may supply `--baseline-root` and `--stage2b-reference-root`; these overrides are recorded in the experiment identity.

## Reproduce

From the repository root on Windows PowerShell:

```powershell
python -m pip install -r ".\Stage 2B.1\requirements.txt"
python ".\Stage 2B.1\stage2b\Stock_Alert_Stage2B_1_Dynamic_Management.py" --sanity
python ".\Stage 2B.1\stage2b\Stock_Alert_Stage2B_1_Dynamic_Management.py"
```

From a POSIX shell:

```bash
python -m pip install -r "Stage 2B.1/requirements.txt"
python "Stage 2B.1/stage2b/Stock_Alert_Stage2B_1_Dynamic_Management.py" --sanity
python "Stage 2B.1/stage2b/Stock_Alert_Stage2B_1_Dynamic_Management.py"
```

Always run the sanity command first. A D0 mismatch, any non-zero D1–D6 accepted-trading parity difference, look-ahead, accounting failure, source/data mutation, or behavior-change blocker causes a fail-closed stop before later diagnostics.

## Identity and scope

The package hash is derived from sorted normalized repository-relative source paths plus each file's exact SHA-256. The frozen manifest and every CSV are verified before and after a run. Machine-specific absolute paths are excluded from experiment identity.

This is historical research software, not investment advice. Current-universe survivorship bias, daily OHLC sequencing ambiguity, multiple-hypothesis selection, the inherited holiday-short-week delay, and generic bps costs remain material limitations.
