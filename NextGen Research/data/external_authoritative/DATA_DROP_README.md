# Authoritative data drop

Place legitimately obtained official files below this directory. Raw files are local-only and ignored by Git.

| Folder | Expected official product | Formats | Target coverage |
|---|---|---|---|
| `nse_security_master/` | Dated NSE Capital Market security/reference files | CSV | 2016-01-01–2026-10-03 |
| `nse_historical_eod/` | NSE Capital Market EOD/security/trade detail | CSV | 2016-01-01–2026-10-03 |
| `nifty_constituents/` | NSE Indices historical broad-index constituents | CSV | Prefer 2016-01-01–2026-10-03; minimum bounded continuous period accepted |
| `nse_corporate_actions/` | NSE official corporate actions | CSV | Same period as research data |
| `bse_reference/` | BSE official reference/corporate data | CSV | Optional corroboration |

Do not rename source columns. Each supported CSV must have exactly the headers in the corresponding schema under `authoritative_data/schemas/`; unknown columns fail closed. Retain the provider's original filename and accompanying licence or delivery note.

Example offline ingestion:

```powershell
python -m authoritative_data.cli ingest --source NIFTY_CONSTITUENTS --input "data/external_authoritative/nifty_constituents/file.csv" --archive-id OFFICIAL_DELIVERY_001 --output "results/imported_nifty_constituents.json"
```

Run validation with:

```powershell
python tests/run_nextgen_authoritative_data_tests.py
```

The tool calculates the raw-byte SHA-256, records parser version and provenance, and writes only the requested derived artifact. It performs no upload or network call. Raw paid/licensed files remain gitignored and must not be committed.
