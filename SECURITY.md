# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 1.0.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability in BackupPilot, please report it responsibly:

1. **Do not** open a public GitHub issue for security vulnerabilities.
2. Email the maintainer directly or use GitHub's private vulnerability reporting feature.
3. Include a description of the vulnerability, steps to reproduce, and potential impact.
4. You will receive an acknowledgment within 48 hours.

## Security Design Principles

### XML Parsing
BackupPilot uses `defusedxml` instead of Python's stdlib `xml.etree.ElementTree` to parse OPNsense configuration files. This prevents:
- XML External Entity (XXE) attacks
- XML bomb (billion laughs) denial of service
- External DTD retrieval

### Subprocess Execution
All subprocess calls follow these security practices:
- Executables are resolved to absolute paths via `shutil.which()` before invocation
- `shell=True` is never used
- All subprocess calls have timeout limits (60-300 seconds)
- `# nosec` annotations document intentional bandit suppressions with rationale

### File Permissions
- Config directory (`~/.backuppilot/`): mode 0o700 (owner-only access)
- Config file (`config.yaml`): mode 0o600 (owner read/write only)
- History database (`history.db`): mode 0o600 (owner read/write only)

### Credential Handling
- No credentials are stored in config files
- Signal API credentials are read from environment variables only
- No secrets are hardcoded in source code

### Network Access
- Signal notifications use `urllib` with explicit timeout (10 seconds)
- rclone commands for GDrive access use the user's local rclone configuration
- No other outbound network connections are made

### Docker Security
- Multi-stage build minimizes attack surface
- Runs as non-root user (`backuppilot`)
- Backup directories mounted read-only
- No privileged capabilities required

## Dependencies

BackupPilot's runtime dependencies are minimal and well-maintained:
- `click` - CLI framework (widely audited)
- `defusedxml` - Secure XML parsing (security-focused library)
- `pyyaml` - YAML parsing with `safe_load` only (no arbitrary code execution)

Run `pip-audit` to check for known vulnerabilities:
```bash
pip-audit
```

Generate an SBOM with:
```bash
cyclonedx-py environment -o sbom.json
```
