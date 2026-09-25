# Historical Point-in-Time Policy

Historical decisions may use only information knowable by the recorded as-of cutoff. Future articles, future filings, later revision leakage, future prices, and event timestamps reconstructed without provenance are prohibited.

Publication, observation, and retrieval timestamps remain separate. Missing timestamps stay missing and restrict eligibility; they are not silently replaced by one another. Corrections and revisions are versioned with their actual availability times. Raw evidence should be immutable and content-hashed where practical. Derived records bind each dependency ID directly to its immutable hash and type, and retain entity/source registry snapshot IDs, versions and hashes, code identity, and the as-of cutoff. Ticker aliases and entities resolve against the acquisition-time registry snapshot, never today's mapping. JSON Schema expresses the timestamp-order invariant but cannot compare timestamps numerically; future ingestion runtime validation must enforce it.

Analogue outcome windows may be computed only as labels after the historical decision snapshot has been frozen. They must never enter analogue selection features or historical decision inputs. Any PIT violation invalidates the affected evaluation.
