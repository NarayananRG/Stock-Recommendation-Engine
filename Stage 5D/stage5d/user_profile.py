from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .horizon import HorizonPreference


def _money(value: object) -> Decimal:
    amount = Decimal(str(value))
    if not amount.is_finite() or amount <= 0:
        raise ValueError("capital ceiling must be a positive finite INR amount")
    return amount


@dataclass(frozen=True)
class InvestmentProfile:
    profile_version: int
    effective_timestamp: str
    maximum_total_capital_inr: Decimal
    preferred_horizon: HorizonPreference
    previous_profile_version: int | None = None
    user_note: str | None = None

    @property
    def capital_ceiling_inr(self) -> Decimal:
        """Version-record alias used by portfolio accounting outputs."""
        return self.maximum_total_capital_inr

    def to_dict(self) -> dict[str, object]:
        return {
            "profile_version": self.profile_version,
            "effective_timestamp": self.effective_timestamp,
            "maximum_total_capital_inr": float(self.maximum_total_capital_inr),
            "capital_ceiling_inr": float(self.maximum_total_capital_inr),
            "preferred_horizon": self.preferred_horizon.value,
            "previous_profile_version": self.previous_profile_version,
            "user_note": self.user_note,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "InvestmentProfile":
        capital_value = payload["maximum_total_capital_inr"] if "maximum_total_capital_inr" in payload else payload["capital_ceiling_inr"]
        if "maximum_total_capital_inr" in payload and "capital_ceiling_inr" in payload and _money(payload["maximum_total_capital_inr"]) != _money(payload["capital_ceiling_inr"]):
            raise ValueError("profile capital fields disagree")
        return cls(
            profile_version=int(payload["profile_version"]),
            effective_timestamp=str(payload["effective_timestamp"]),
            maximum_total_capital_inr=_money(capital_value),
            preferred_horizon=HorizonPreference(str(payload["preferred_horizon"])),
            previous_profile_version=(None if payload.get("previous_profile_version") is None else int(payload["previous_profile_version"])),
            user_note=(None if payload.get("user_note") is None else str(payload["user_note"])),
        )


class ProfileStore:
    """Append-only profile versions stored as immutable JSON records."""

    def __init__(self, history_directory: Path | str):
        self.history_directory = Path(history_directory)

    def _records(self) -> list[Path]:
        return sorted(self.history_directory.glob("profile_v*.json")) if self.history_directory.exists() else []

    def load(self, version: int | None = None) -> InvestmentProfile:
        records = self._records()
        if not records:
            raise FileNotFoundError("no persisted investment profile exists")
        path = records[-1] if version is None else self.history_directory / f"profile_v{version:06d}.json"
        if not path.exists():
            raise FileNotFoundError(f"profile version {version} does not exist")
        return InvestmentProfile.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(
        self,
        maximum_total_capital_inr: object,
        preferred_horizon: HorizonPreference | str,
        *,
        user_note: str | None = None,
        effective_timestamp: str | None = None,
    ) -> InvestmentProfile:
        horizon = preferred_horizon if isinstance(preferred_horizon, HorizonPreference) else HorizonPreference(str(preferred_horizon))
        previous = self.load() if self._records() else None
        version = 1 if previous is None else previous.profile_version + 1
        timestamp = effective_timestamp or datetime.now(timezone.utc).isoformat()
        # Reject malformed timestamps before persisting an immutable record.
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        profile = InvestmentProfile(version, timestamp, _money(maximum_total_capital_inr), horizon, None if previous is None else previous.profile_version, user_note)
        self.history_directory.mkdir(parents=True, exist_ok=True)
        target = self.history_directory / f"profile_v{version:06d}.json"
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(profile.to_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")
        return profile
