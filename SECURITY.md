# Security policy

einvoice-xml parses invoices that come from third parties and treats them as hostile. Its
limits and its parsing are described in the [README](README.md#security).

## Supported versions

Security fixes are made for the latest released minor version. Please update to the
latest release before reporting.

## Reporting a vulnerability

Please do **not** open a public issue for a vulnerability. Report it privately to:

**security@ext.dev**

Include what you found, how to reproduce it, and which version you use. **Never send a
real invoice or real personal or company data** — a synthetic example is enough.

We acknowledge a report within a few working days, keep you informed about the fix, and
credit you in the changelog if you wish.

## Scope

In scope: the code in this repository and the published package — for example input that
makes `read` raise, hang or exhaust memory, resolves an entity, or reaches the network or
the file system.

Out of scope: `pypdf`, `defusedxml` and other dependencies (please report to them
directly), and whether a document that passes this library is valid under tax law.
