# Trade Thesis Policy

A thesis is persistent, versioned state linked to the original recommendation. It preserves entry rationale, supporting evidence, known risks, initial entry range, references to every partial or complete Stage 5D.5 fill, a deterministic aggregate fill, initial/current stop and target, invalidation conditions, holding horizon, portfolio context, and every review. Fill references remain read-only production-control identities; Stage 6 never duplicates or rewrites their authority. Each thesis version records its engine version, code commit, decision cutoff, exact input IDs and hashes, prior-version hash, and record hash.

Daily review asks: **What material information changed since entry or the previous session?** It does not rebuild an unrelated opinion. Review outcomes are:

- `THESIS_STRENGTHENED`: new reliable evidence improves the stated rationale without erasing known risks.
- `THESIS_UNCHANGED`: no material supported change.
- `THESIS_WEAKENED`: supported adverse change that does not yet satisfy an invalidation condition.
- `THESIS_INVALIDATED`: a recorded invalidation condition is met by adequate evidence.

A newly ranked candidate does not automatically replace a healthy holding. Replacement, reduction, stop, and target proposals remain shadow-only and require portfolio context, evidence, and immutable change history.
