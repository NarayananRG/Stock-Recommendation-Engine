"""Non-trading command line operator for Stage 6.8C observations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .checkpoint_builder import build_checkpoint, derive_final_exit, determine_due_checkpoints
from .control_reader import Stage5DControlReader
from .cohort_guard import verify_active_cohort
from .observation_store import ProspectiveObservationStore
from .recommendation_envelope import build_recommendation_envelope


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _store(args, cohort):
    return ProspectiveObservationStore(args.observation_database, args.repo_root, cohort)


def run(args):
    cohort = verify_active_cohort(args.repo_root, args.activation_record)
    if args.action == "verify-cohort":
        return {"status": "PASS", "cohort_fingerprint": cohort}
    with _store(args, cohort) as store:
        if args.action == "status":
            return store.integrity_check()
        if args.action == "create-envelope":
            envelope = build_recommendation_envelope(
                control_database=args.control_database, prospective_database=args.prospective_database,
                recommendation_id=args.recommendation_id, cohort_fingerprint=cohort,
                stage4a3_snapshot=_json(args.stage4a3_snapshot),
                creation_context=None if args.creation_context is None else _json(args.creation_context))
            return store.persist_envelope(envelope)
        if args.action in ("due-checkpoints", "build-checkpoint"):
            row = store.connection.execute("SELECT canonical_json FROM recommendation_audit_envelopes WHERE recommendation_id=?", (args.recommendation_id,)).fetchone()
            if row is None:
                raise ValueError("RECOMMENDATION_ENVELOPE_REQUIRED")
            inputs = _json(args.checkpoint_input)
            envelope = json.loads(row[0])
            if args.action == "due-checkpoints":
                return {"status": "PASS", "due_checkpoints": determine_due_checkpoints(
                    decision_date=envelope["decision_date"], completed_session_dates=inputs["completed_session_dates"],
                    existing_checkpoint_types=inputs.get("existing_checkpoint_types", ()),
                    final_exit_completed=inputs.get("final_exit_completed", False))}
            final_exit = None
            if args.checkpoint_type == "FINAL_EXIT":
                with Stage5DControlReader(args.control_database) as reader:
                    final_exit = derive_final_exit(reader, args.recommendation_id, args.checkpoint_cutoff_utc)
            checkpoint = build_checkpoint(
                envelope=envelope, checkpoint_type=args.checkpoint_type,
                checkpoint_cutoff_utc=args.checkpoint_cutoff_utc,
                market_data_manifest=inputs["market_data_manifest"],
                thesis_records=inputs.get("thesis_records", []), final_exit=final_exit)
            return store.persist_checkpoint(checkpoint)
    raise ValueError("UNKNOWN_ACTION")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Stage 6.8C shadow-only prospective observation operator")
    parser.add_argument("action", choices=("verify-cohort", "create-envelope", "due-checkpoints", "build-checkpoint", "status"))
    parser.add_argument("--repo-root", required=True); parser.add_argument("--activation-record", required=True)
    parser.add_argument("--observation-database"); parser.add_argument("--control-database"); parser.add_argument("--prospective-database")
    parser.add_argument("--recommendation-id"); parser.add_argument("--stage4a3-snapshot"); parser.add_argument("--creation-context")
    parser.add_argument("--checkpoint-type"); parser.add_argument("--checkpoint-cutoff-utc"); parser.add_argument("--checkpoint-input")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run(args), sort_keys=True)); return 0
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, sort_keys=True)); return 1


if __name__ == "__main__":
    raise SystemExit(main())
