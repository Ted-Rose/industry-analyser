"""Helpers for normalizing the Postgres CA cert passed via env vars.

The cert can arrive as a single- or multi-cert chain, with real
newlines, literal ``\\n`` escapes, or flattened to a single line with
spaces (some env-var UIs strip newlines). ``format_db_ssl_pem``
normalizes all of these to canonical 64-column PEM.
"""
import re
import textwrap

_CERT_BLOCK_RE = re.compile(
    r'-----BEGIN CERTIFICATE-----([^-]*)-----END CERTIFICATE-----'
)


def normalize_db_ssl_pem_raw(raw: str) -> str:
    if not raw:
        return ''
    s = raw.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        s = s[1:-1]
    s = s.replace('\\n', '\n')
    return s.strip()


def format_db_ssl_pem(raw: str) -> str:
    pem = normalize_db_ssl_pem_raw(raw)
    certs = _CERT_BLOCK_RE.findall(pem)
    if not certs:
        return pem
    blocks = [
        '-----BEGIN CERTIFICATE-----\n'
        f'{textwrap.fill("".join(body.split()), 64)}\n'
        '-----END CERTIFICATE-----'
        for body in certs
    ]
    return '\n'.join(blocks) + '\n'
