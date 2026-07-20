---
issue: https://github.com/Toilal/fastapi-router-variants/issues/16
mr:
branch: fix/16-preserve-dependency-overrides
model: GPT-5
started_at: 2026-07-20T15:16:10Z
completed_at:
---

# Implementation notes: preserve dependency overrides

## Design decisions

- Rebind only routes extracted from a transparent included-router wrapper; direct routes and non-transparent wrappers retain their existing serving context.
- Rebuild both HTTP and WebSocket ASGI handlers because FastAPI freezes the dependency override provider when each handler is constructed.

## Tradeoffs

- The compatibility helper necessarily uses FastAPI's handler builders until FastAPI exposes a public route re-parenting API.
