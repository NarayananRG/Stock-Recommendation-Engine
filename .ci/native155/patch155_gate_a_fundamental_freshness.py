from __future__ import annotations

import os
from pathlib import Path


ENGINE_ROOT = Path(os.environ["SRE_ENGINE_ROOT"]).resolve()
FUNDAMENTALS = ENGINE_ROOT / "stock_app" / "fundamentals.py"
MONITORING = ENGINE_ROOT / "stock_app" / "monitoring.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_fundamentals() -> None:
    text = FUNDAMENTALS.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''            source="OFFICIAL_LEG5_PIT_RECOVERY" if any(str(o.source_url).startswith("LEG5_AUTHORITATIVE:") for o in available) else "OFFICIAL_NSE_SAMPLE_CACHE",
            values=values,
            features=features,
            data_quality={"verification": "VERIFIED_OFFICIAL_PIT_RECOVERY" if any(str(o.source_url).startswith("LEG5_AUTHORITATIVE:") for o in available) else "VERIFIED_OFFICIAL_SAMPLE", "completeness": completeness, "contract": SNAPSHOT_CONTRACT_VERSION},''',
        '''            source=self._source_label(latest_rows.values()),
            values=values,
            features=features,
            data_quality={"verification": self._verification_label(latest_rows.values()), "completeness": completeness, "contract": SNAPSHOT_CONTRACT_VERSION},''',
        "snapshot provenance",
    )

    text = replace_once(
        text,
        '''        source = "OFFICIAL_LEG5_PIT_RECOVERY" if self._authoritative_observation_paths else "OFFICIAL_NSE_SAMPLE_CACHE"''',
        '''        source = (
            "OFFICIAL_PHASE5_CANONICAL_PANEL"
            if any(path.name == "canonical_feature_panel.csv" for path in self._authoritative_observation_paths)
            else ("OFFICIAL_LEG5_PIT_RECOVERY" if self._authoritative_observation_paths else "OFFICIAL_NSE_SAMPLE_CACHE")
        )''',
        "refresh provenance",
    )

    text = replace_once(
        text,
        '''                    "source_coverage": ("OFFICIAL_LEG5_PIT_RECOVERY" if any(str(o.source_url).startswith("LEG5_AUTHORITATIVE:") for o in obs) else "OFFICIAL_NSE_SAMPLE_CACHE") if obs else MISSING,''',
        '''                    "source_coverage": self._source_label(obs) if obs else MISSING,''',
        "coverage provenance",
    )

    load_anchor = '''        authoritative: list[FundamentalObservation] = []
        self._authoritative_observation_paths = []
        candidates = ['''
    load_replacement = '''        authoritative: list[FundamentalObservation] = []
        self._authoritative_observation_paths = []

        # Phase 5 is the official, point-in-time panel already bundled for Fundamental V3.
        # Load it first so the legacy freshness monitor observes the same evidence path.
        canonical_panel = (
            self.repo_root
            / "NextGen Research"
            / "results"
            / "fundamental_v2_phase2a4_feature_panel"
            / "canonical_feature_panel.csv"
        )
        if canonical_panel.exists():
            parsed = self._parse_phase5_canonical_panel(canonical_panel)
            if parsed:
                authoritative.extend(parsed)
                self._authoritative_observation_paths.append(canonical_panel)

        candidates = ['''
    text = replace_once(text, load_anchor, load_replacement, "canonical discovery")

    parser_anchor = '''    def _parse_authoritative_quarterly_csv(self, path: Path) -> list[FundamentalObservation]:'''
    parser = '''    def _parse_phase5_canonical_panel(self, path: Path) -> list[FundamentalObservation]:
        """Adapt verified Phase 5 wide rows without inventing unavailable facts."""
        try:
            with path.open(newline="", encoding="utf-8-sig") as handle:
                rows = list(csv.DictReader(handle))
        except (OSError, UnicodeDecodeError, csv.Error):
            return []
        if not rows:
            return []

        rows_by_symbol: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            symbol = self._clean_symbol(row.get("symbol"))
            if symbol:
                rows_by_symbol.setdefault(symbol, []).append(row)

        accepted_statuses = {"SELECTED", "SELECTED_EQUIVALENT_DUPLICATES"}
        feature_map = {
            "REVENUE": ("revenue", "INR"),
            "PAT": ("net_profit", "INR"),
            "EPS": ("eps", "INR_PER_SHARE"),
            "TOTAL_ASSETS": ("total_assets", "INR"),
            "OPERATING_CASH_FLOW": ("operating_cash_flow", "INR"),
            "CASH_AND_EQUIVALENTS": ("cash_and_equivalents", "INR"),
        }
        observations: list[FundamentalObservation] = []
        for symbol, symbol_rows in rows_by_symbol.items():
            bases = sorted({str(row.get("reporting_basis") or "").strip().upper() for row in symbol_rows})
            chosen_basis = "CONSOLIDATED" if "CONSOLIDATED" in bases else (bases[0] if bases else "")
            for row in symbol_rows:
                if str(row.get("reporting_basis") or "").strip().upper() != chosen_basis:
                    continue
                if str(row.get("archive_gap") or "").strip().lower() in {"1", "true", "yes"}:
                    continue
                period = str(row.get("quarter_end") or "").strip()
                publication = str(row.get("availability_ts") or "").strip()
                if not period or not publication:
                    continue
                try:
                    _parse_date(publication)
                except (TypeError, ValueError):
                    continue
                document_id = str(row.get("event_id") or row.get("source_content_sha256") or "").strip()
                if not document_id:
                    document_id = f"phase5:{symbol}:{period}:{chosen_basis}"
                source_domain = str(row.get("domain") or "NSE_OFFICIAL_XBRL").strip()
                for feature, (field, unit) in feature_map.items():
                    status = str(row.get(f"{feature}__status") or "").strip().upper()
                    if status not in accepted_statuses:
                        continue
                    value = self._to_float(row.get(f"{feature}__value"))
                    if value is None:
                        continue
                    observations.append(FundamentalObservation(
                        symbol=symbol,
                        company_id=symbol,
                        exchange="NSE",
                        fiscal_period=period,
                        period_type="QUARTERLY",
                        period_start="",
                        period_end=period,
                        reporting_label=period,
                        publication_timestamp=publication,
                        source_type="OFFICIAL_NSE",
                        source_url=f"PHASE5_CANONICAL_PANEL:{path.name}|{source_domain}",
                        source_document_id=document_id,
                        retrieved_at=publication,
                        field=field,
                        raw_value=value,
                        normalized_value=value,
                        unit=unit,
                        currency="INR",
                        restatement_status=str(row.get("submission_type") or "ORIGINAL"),
                        verification_status="VERIFIED_OFFICIAL",
                    ))
        return observations

    @staticmethod
    def _source_label(observations: Any) -> str:
        rows = list(observations)
        if any(str(row.source_url).startswith("PHASE5_CANONICAL_PANEL:") for row in rows):
            return "OFFICIAL_PHASE5_CANONICAL_PANEL"
        if any(str(row.source_url).startswith("LEG5_AUTHORITATIVE:") for row in rows):
            return "OFFICIAL_LEG5_PIT_RECOVERY"
        return "OFFICIAL_NSE_SAMPLE_CACHE"

    @staticmethod
    def _verification_label(observations: Any) -> str:
        source = FundamentalSnapshotService._source_label(observations)
        if source == "OFFICIAL_PHASE5_CANONICAL_PANEL":
            return "VERIFIED_OFFICIAL_PHASE5_CANONICAL_PANEL"
        if source == "OFFICIAL_LEG5_PIT_RECOVERY":
            return "VERIFIED_OFFICIAL_PIT_RECOVERY"
        return "VERIFIED_OFFICIAL_SAMPLE"

    def _parse_authoritative_quarterly_csv(self, path: Path) -> list[FundamentalObservation]:'''
    text = replace_once(text, parser_anchor, parser, "canonical parser")
    FUNDAMENTALS.write_text(text, encoding="utf-8")


def patch_monitoring() -> None:
    text = MONITORING.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''row["data_freshness"].get("fundamental") in {"UNAVAILABLE", "STALE"}''',
        '''row["data_freshness"].get("fundamental") in {"UNAVAILABLE", "STALE", "VERY_STALE"}''',
        "summary very-stale accounting",
    )
    text = replace_once(
        text,
        '''        if fundamental.data_freshness in {"STALE", "UNAVAILABLE"}:
            reasons.append("FUNDAMENTAL_DATA_STALE")''',
        '''        if fundamental.data_freshness == "UNAVAILABLE":
            reasons.append("FUNDAMENTAL_DATA_UNAVAILABLE")
        elif fundamental.data_freshness in {"STALE", "VERY_STALE"}:
            reasons.append("FUNDAMENTAL_DATA_STALE")''',
        "distinct freshness diagnostics",
    )
    MONITORING.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    if not FUNDAMENTALS.exists() or not MONITORING.exists():
        raise SystemExit(f"reconstructed engine is incomplete: {ENGINE_ROOT}")
    patch_fundamentals()
    patch_monitoring()
    print(f"Gate A freshness patch applied to {ENGINE_ROOT}")
