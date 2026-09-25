# Decision Authority Policy

Stage 5D.5 at tag `stage5d5-live-paper-runner-baseline` is the official production-control system. All Stage 6 outputs begin and remain `SHADOW_ONLY` unless a later, explicit, component-specific promotion gate changes that authority.

Stage 6 must not create or cancel a BUY, change quantity, stop, or target, execute or request a SELL, reduce a position, replace a holding, place a broker instruction, or mutate Stage 5D.5 state. Human-readable words such as `ENTRY_VALID`, `REDUCE`, or `EXIT` are research labels only. They are not permissions or executable commands.

No passing test, model score, historical result, or prospective result automatically grants authority. A consumer must reject any Stage 6 decision whose `authority_mode` is not `SHADOW_ONLY` under the 6.0 contract. Production influence remains false until an approved promotion explicitly changes both policy and machine-readable contracts.
