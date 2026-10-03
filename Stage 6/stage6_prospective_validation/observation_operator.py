"""Non-trading command line operator for Stage 6.8C observations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .activation import verify_activation_record
from .checkpoint_builder import build_checkpoint, derive_final_exit
from .control_reader import Stage5DControlReader
from .cohort_guard import verify_active_cohort
from .observation_store import ProspectiveObservationStore
from .recommendation_envelope import build_recommendation_envelope
from .verified_inputs import MarketArchiveResolver, ProspectiveStoreReader, Stage6ContextReader


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
                activation_record=args.activation_record, stage4a3_root=args.stage4a3_root,
                stage4a3_prospective_root=args.stage4a3_prospective_root,
                stage6_context_database=args.stage6_context_database,
                stage6_context_binding=None if args.creation_context_binding is None else _json(args.creation_context_binding))
            return store.persist_envelope(envelope)
        if args.action in ("due-checkpoints", "build-checkpoint"):
            row = store.connection.execute("SELECT canonical_json FROM recommendation_audit_envelopes WHERE recommendation_id=?", (args.recommendation_id,)).fetchone()
            if row is None:
                raise ValueError("RECOMMENDATION_ENVELOPE_REQUIRED")
            envelope = json.loads(row[0])
            activation = verify_activation_record(args.activation_record)
            with Stage5DControlReader(args.control_database) as reader:
                recommendation = reader.get_recommendation(args.recommendation_id)
                origin_run = reader.get_origin_run(recommendation["allocation_run_id"])
                control_database_id = reader.database_id()
            with ProspectiveStoreReader(args.prospective_database, activation) as prospective:
                origin_session = prospective.origin_session(origin_run, control_database_id)
                existing = [r[0] for r in store.connection.execute("SELECT checkpoint_type FROM benchmark_checkpoints WHERE recommendation_id=?", (args.recommendation_id,))]
                due = prospective.due_checkpoints(origin_session, existing)
                if args.action == "due-checkpoints":
                    return {"status": "PASS", "due_checkpoints": due}
            final_exit = None
            if args.checkpoint_type == "FINAL_EXIT":
                with Stage5DControlReader(args.control_database) as reader:
                    final_exit = derive_final_exit(reader, args.recommendation_id, args.checkpoint_cutoff_utc)
                target_date = final_exit["final_exit_date"]
            else:
                matches = [item for item in due if item["checkpoint_type"] == args.checkpoint_type]
                if len(matches) != 1 or matches[0]["status"] != "DUE":
                    raise ValueError("CHECKPOINT_NOT_DUE_FROM_VERIFIED_SESSION_CHAIN")
                target_date = matches[0]["checkpoint_date"]
            with ProspectiveStoreReader(args.prospective_database, activation) as prospective:
                verified_dates = prospective.session_dates_through(origin_session, target_date)
            market_manifest = MarketArchiveResolver(args.market_archive_directory).resolve(
                ticker=envelope["ticker"], anchor_date=envelope["decision_date"], target_date=target_date,
                checkpoint_cutoff_utc=args.checkpoint_cutoff_utc, verified_session_dates=verified_dates)
            thesis_records = []
            if args.thesis_binding is not None:
                if args.stage6_thesis_database is None:
                    raise ValueError("STAGE6_THESIS_DATABASE_REQUIRED")
                with Stage6ContextReader(args.stage6_thesis_database) as context_reader:
                    value, binding = context_reader.resolve(_json(args.thesis_binding), cutoff_utc=args.checkpoint_cutoff_utc,
                        recommendation_id=envelope["recommendation_id"], signal_id=envelope["signal_id"], ticker=envelope["ticker"])
                thesis_records = [{"recorded_at_utc": value.get("recorded_at_utc") or value.get("decision_cutoff") or value.get("review_cutoff"),
                    "current_thesis_state": value.get("current_thesis_state", value.get("thesis_status", "INDETERMINATE")),
                    "original_thesis_validity_state": value.get("original_thesis_validity_state", "INDETERMINATE"), "binding": binding}]
            checkpoint = build_checkpoint(
                envelope=envelope, checkpoint_type=args.checkpoint_type,
                checkpoint_cutoff_utc=args.checkpoint_cutoff_utc,
                market_data_manifest=market_manifest,
                thesis_records=thesis_records, thesis_records_verified=True, final_exit=final_exit)
            return store.persist_checkpoint(checkpoint)
    raise ValueError("UNKNOWN_ACTION")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Stage 6.8C shadow-only prospective observation operator")
    parser.add_argument("action", choices=("verify-cohort", "create-envelope", "due-checkpoints", "build-checkpoint", "status"))
    parser.add_argument("--repo-root", required=True); parser.add_argument("--activation-record", required=True)
    parser.add_argument("--observation-database"); parser.add_argument("--control-database"); parser.add_argument("--prospective-database")
    parser.add_argument("--recommendation-id"); parser.add_argument("--stage4a3-root"); parser.add_argument("--stage4a3-prospective-root")
    parser.add_argument("--stage6-context-database"); parser.add_argument("--creation-context-binding")
    parser.add_argument("--checkpoint-type"); parser.add_argument("--checkpoint-cutoff-utc"); parser.add_argument("--market-archive-directory")
    parser.add_argument("--stage6-thesis-database"); parser.add_argument("--thesis-binding")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run(args), sort_keys=True)); return 0
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": str(exc)}, sort_keys=True)); return 1


if __name__ == "__main__":
    raise SystemExit(main())
