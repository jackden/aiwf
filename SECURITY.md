# Security

AIWF is a repository-native workflow tool. Security reports are most useful when
they focus on path handling, public export boundaries, legacy migration behavior,
or accidental exposure of private workflow data.

Please report suspected vulnerabilities using GitHub private vulnerability
reporting if it is available for this repository. If private reporting is not
available, open a minimal public issue that states a security report is available
without including exploit details or sensitive data.

Useful reports include:

- affected version, commit, or release tag
- steps to reproduce
- expected and actual behavior
- impact, especially possible private record, event, dataset, credential,
  internal URL, or local-path exposure

Do not include secrets, credentials, private workflow records, datasets, internal
URLs, or other sensitive information in public issues or pull requests.

Security fixes should preserve finalized workflow evidence. If a finalized
record needs interpretation or correction, use a follow-up errata task instead
of rewriting finalized evidence.
