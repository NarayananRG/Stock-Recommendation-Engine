# Trade Thesis Policy

A thesis is persistent, versioned state linked to the original recommendation. It preserves entry rationale, supporting evidence, known risks, initial entry range, actual fill when available, initial/current stop and target, invalidation conditions, holding horizon, portfolio context, and every review.

Daily review asks: **What material information changed since entry or the previous session?** It does not rebuild an unrelated opinion. Review outcomes are:

- `THESIS_STRENGTHENED`: new reliable evidence improves the stated rationale without erasing known risks.
- `THESIS_UNCHANGED`: no material supported change.
- `THESIS_WEAKENED`: supported adverse change that does not yet satisfy an invalidation condition.
- `THESIS_INVALIDATED`: a recorded invalidation condition is met by adequate evidence.

A newly ranked candidate does not automatically replace a healthy holding. Replacement, reduction, stop, and target proposals remain shadow-only and require portfolio context, evidence, and immutable change history.
