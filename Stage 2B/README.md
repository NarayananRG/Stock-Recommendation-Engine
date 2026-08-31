# Stage 2B — Dynamic Daily Trade Management

Stage 2B is a deterministic post-entry research layer over the immutable Stage 2.2.2 Final baseline. It consumes the accepted BUY/STRONG BUY candidate artifact and reuses the frozen Stage 2.2.1 order, ranking, fill, sizing, cash, slippage, and cost implementation. It does not regenerate or reinterpret entries.

## Layout

- `stage2b/Stock_Alert_Stage2B_Dynamic_Management.py` — runner and dynamic portfolio engine
- `stage2b/policies.py` — preregistered D1–D6 after-close decisions
- `stage2b/calibration.py` — past-only hierarchical empirical calibration
- `stage2b/validation.py` — immutable hash gates and D0 comparison
- `config/stage2b_policy_config.json` — fixed research configuration
- `stage2b/tests/sanity_results/` — required two-ticker sanity artifacts
- `stage2b/results/` — official full-history compatibility and 2016–2026 pseudo-OOS artifacts
- `Stage2B_Delivery_Report.md` — findings, hashes, validation, and limitations

## Run

Use the bundled Python runtime that contains pandas and NumPy:

```powershell
& 'C:\Users\Narayanan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' '.\Stage 2B\stage2b\Stock_Alert_Stage2B_Dynamic_Management.py' --sanity
& 'C:\Users\Narayanan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' '.\Stage 2B\stage2b\Stock_Alert_Stage2B_Dynamic_Management.py'
```

The full run stops before dynamic research unless D0 reproduces the accepted T2_63D signals, orders, trades, and equity with zero differences.

This is historical research, not investment advice or a live/paper-trading system.
