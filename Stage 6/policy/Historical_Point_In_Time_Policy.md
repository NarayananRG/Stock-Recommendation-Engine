# Historical Point-in-Time Policy

Historical decisions may use only information knowable by the recorded as-of cutoff. Future articles, future filings, later revision leakage, future prices, and event timestamps reconstructed without provenance are prohibited.

Publication, observation, and retrieval timestamps remain separate. Missing timestamps stay missing and restrict eligibility; they are not silently replaced by one another. Corrections and revisions are versioned with their actual availability times. Raw evidence should be immutable and content-hashed where practical. Derived records must retain input IDs, hashes, entity/source registry versions, code identity, and the as-of cutoff so eligibility can be reproduced. JSON Schema expresses the timestamp-order invariant but cannot compare timestamps numerically; future ingestion runtime validation must enforce it.

Analogue outcome windows may be computed only as labels after the historical decision snapshot has been frozen. They must never enter analogue selection features or historical decision inputs. Any PIT violation invalidates the affected evaluation.
