# Security policy

CML Lab Builder is a desktop app that holds your CML credentials and drives your CML controller. This file explains
how to report a problem, what the app protects against, and how releases are signed.

## Reporting a vulnerability
Please **do not open a public issue** for a security problem. Use GitHub's private vulnerability reporting:
*Security > Report a vulnerability* on https://github.com/Specops13/cml-lab-builder. Include the version
(*Settings > Updates* or `cmllab version`), your OS and steps to reproduce. You should get an answer within a week;
fixes ship as a patch release that installed apps offer by themselves.

Supported versions: the latest release. Fixes are not backported.

## Threat model (short)
- The web UI runs on your computer and listens on 127.0.0.1. Websites you visit, other local users and other local
  programs must not be able to use it. Protections: a Host allowlist (DNS rebinding), cross-site / CSRF checks
  (`Sec-Fetch-Site`, `Origin`, and a required `X-CMLLab-Request` header on every state-changing request), no CORS,
  a per-launch access token (desktop app), and a strict CSP with no inline script.
- Lab files, courses and the online library are **data** (YAML, regex), loaded with `yaml.safe_load`, size-limited,
  path-checked (zip-slip) and, for library installs, verified against a sha256.
- Updates are code. They must be signed with the release key (below) and match `SHA256SUMS.txt`, the per-file
  manifest, the version and the runtime before they are installed; a patch that cannot start is rolled back.
- Secrets (CML password, device passwords, AI API key) live in the OS keyring, or in a `secrets.json` that only you
  can read (0600) when there is no keyring. They are never written to `settings.json`, returned by the API or logged.
- Out of scope: a compromised user account or machine, and the security of the CML controller itself.

## Release signing
Since 3.3.0 every release carries detached **Ed25519** signatures:

| Asset | Signature |
|---|---|
| `SHA256SUMS.txt` (covers every asset of the release) | `SHA256SUMS.txt.sig` |
| `cml-lab-builder-patch-<version>.zip` (also for offline *Install update from file*) | `cml-lab-builder-patch-<version>.zip.sig` |

A `.sig` file is JSON: `{"format": 1, "alg": "ed25519", "key_id": "<first 16 hex of sha256(public key)>", "sig": "<base64>"}`.

The public keys the app trusts are in `cmllab/signing.py` (`TRUSTED_KEYS`). The current release key:

```
key name:   release-2026
public key: 48f799c3e8938c8be616cde0c4c8bf1927aeea8ab9f5b8cd310efa04e294c6be   (raw Ed25519, hex)
```

3.3.0 and later refuse an update whose signature is missing, made with an unknown key, or invalid. Versions up to
3.2.0 do not know about signatures and keep verifying `SHA256SUMS.txt` only, so they can still update to 3.3.0 (which
is the last update they install without a signature check).

Verify a download by hand (Python with `cryptography`):

```python
import base64, json
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex("48f799c3e8938c8be616cde0c4c8bf1927aeea8ab9f5b8cd310efa04e294c6be"))
sig = json.load(open("SHA256SUMS.txt.sig"))
pub.verify(base64.b64decode(sig["sig"]), open("SHA256SUMS.txt", "rb").read())   # raises InvalidSignature if bad
```

then `sha256sum -c SHA256SUMS.txt --ignore-missing`.

### The private key
The private key is **never** in this repository (`.signing/` and `*.key` are git-ignored, and a test fails if a
private key appears in the tree). The maintainer keeps it offline, with a backup, and signs the published
`SHA256SUMS.txt` and the patch after CI has built them. It can optionally be stored as the GitHub Actions secret
`RELEASE_SIGNING_KEY` so CI can sign.

### Key rotation
1. Generate a new key pair and add its public key to `TRUSTED_KEYS` **next to** the old one; release that version
   signed with the **old** key (installed apps only trust keys they already have).
2. From the next release on, sign with the new key. Remove the old key from `TRUSTED_KEYS` one or two releases later.
3. If the private key is **compromised**: remove its public key from `TRUSTED_KEYS` at once, publish a release signed
   with a new key and tell users (release notes, README) to download it in full, because apps that only trust the
   compromised key cannot tell a genuine update from a forged one.

## Development checks
CI runs the test suite (which includes `tests/test_web_security.py`), a security lint (`ruff check`, `S` rules =
flake8-bandit, see `pyproject.toml`) and `pip-audit` against the installed dependencies. Dependabot alerts and
private vulnerability reporting should be enabled on the repository.
