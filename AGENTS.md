# AIOps-X Enterprise Working Agreement

## Scope and safety

- Only read and modify this repository unless the user explicitly supplies another file.
- Preserve unknown files and existing behavior. Inspect first, then make small, reversible changes.
- Never commit credentials, tokens, private keys, authenticated URLs, or production data.
- Keep demo and test data under `tests/fixtures/` or an explicitly named development seed.

## Architecture

- Keep the control plane as a FastAPI modular monolith with explicit domain boundaries.
- Keep the Web UI, worker, AI engine, and Edge Agent independently deployable.
- Put all public APIs under `/api/v1` and use versioned event contracts.
- Core business logic may depend on interfaces, not directly on Prometheus, NATS, MinIO, Vault, or a model vendor.
- Do not access another module's tables directly. Use application services, domain events, or published interfaces.

## Security and evidence

- GxP assets default to no automatic remediation. R2+ actions require the configured approval policy.
- The AI engine can recommend only structured actions backed by evidence; it never executes commands.
- Store only `credential_ref` values in PostgreSQL. Secret values belong in the configured secret provider.
- Never return stack traces, SQL, tokens, internal paths, or unsanitized command output through APIs.
- Do not use fake production data, fixed success responses, or fabricated AI/Agent status.

## Definition of done

- Keep code, migrations, tests, deployment files, and documentation in sync.
- Run the relevant lint, type-check, tests, build, migration, Compose validation, and smoke checks.
- Distinguish files changed from runtime behavior verified.
- Update `docs/STATUS.md` with commands actually run, results, gaps, risks, and the next milestone.
