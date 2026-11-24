# JARVIS Security Scanner

The JARVIS runtime now includes a local, read-only static security scanner.

## What it checks

- Credential-like values and private-key material in supported text files.
- Common unsafe Python APIs and configurations, including dynamic evaluation,
  shell-enabled subprocess calls, unsafe deserialization, disabled TLS verification,
  and unsafe YAML loading.

Credential values are never copied into the report. Findings include a rule,
severity, relative file path, line number, and redacted explanation.

## Runtime endpoints

- GET /api/v1/security/status — availability and latest scan summary.
- POST /api/v1/security/scan — run a new scan against the JARVIS project root.
- GET /api/v1/security/report — retrieve the latest JSON report.

JARVIS can also invoke the security.scan_project read-only skill through its
normal agent planner and policy engine.

## Scope and safeguards

- The scan root is fixed by trusted runtime code to the JARVIS project directory.
- No caller-supplied paths, arbitrary commands, shell execution, network requests,
  exploit attempts, or external reconnaissance are accepted.
- Source files are only read. The only write is the generated report at
  data/security-reports/latest.json, using an atomic temporary-file replacement.
- Symlinks, binary files, oversized files, dependency caches, VCS metadata,
  virtual environments, build outputs, and application data are excluded.
- Limits: 3,000 files, 1 MB per file, and 100 MB total scanned content.
- Every API scan is recorded in the JARVIS audit log.
- The scanner does not automatically apply fixes. Any remediation must be reviewed
  and explicitly approved as a separate operation.

## Limitations

This is a lightweight static check, not a full SAST product, dependency audit,
penetration test, or guarantee that the project is secure. Some findings may be
false positives and should be reviewed before remediation.
