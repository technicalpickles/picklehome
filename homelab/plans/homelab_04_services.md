# Services

> **This document has graduated to a reference doc.** The current service registry and deployment pattern live in [`homelab/services/README.md`](../services/README.md). What remains here is the original planning context.
>
> Convention: per `docs/CONVENTIONS.md`, `plans/` is for point-in-time design artifacts. Once the design is load-bearing reference material (i.e. how things actually work, not how we decided to do them), it belongs in a README near the code.

## Original goals (preserved)

The "04" doc was meant to answer: for each service, what is its purpose, where do its compose files and data live, how is it accessed, and what env vars does it need? Those questions are now answered in [services/README.md](../services/README.md).

The deployment pattern itself (file layout per service, on-host paths, Tailscale Services for TLS) is also documented there.
