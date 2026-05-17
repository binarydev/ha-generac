# manual_auth_debug.py — Generac auto-login diagnostic harness

Standalone CLI that mints a valid `app.mobilelinkgen.com` session cookie.
This is now a **diagnostic / regression-test tool**, not the primary
end-user entry point — as of integration version 0.5.0, the HA integration
itself can mint cookies in-process when given email + password (see the
integration README's AUTO_MINT section).

This script imports the integration's `custom_components/generac/auth.py`
directly (via `sys.path` prepend), so it shares the exact same auth flow
as the integration. The two cannot drift.

## When to use it

- Verify the auth flow still works after a Generac / Auth0 / Imperva change
- Manually mint a cookie for paste-only debugging
- Capture verbose redirect logs for a specific failure mode

For day-to-day use, prefer the integration's AUTO_MINT mode.

## Setup

```bash
cd scripts/
/usr/local/opt/python@3.13/bin/python3.13 -m venv .venv
.venv/bin/pip install curl_cffi==0.7.4
```

## Usage

```bash
export GENERAC_EMAIL="you@example.com"
export GENERAC_PASSWORD="..."
.venv/bin/python manual_auth_debug.py
```

Output: one line on stdout — the full `Cookie:` header value. Paste into
the integration's "Session Cookie" field in HA's Reconfigure flow.

## Flags

- `--out PATH` — also write the cookie to a file
- `--verbose` / `-v` — log the redirect chain to stderr
- `--no-device-persistence` — don't persist Auth0 device cookies between runs
- `--impersonate PROFILE` — curl_cffi Chrome impersonation profile (default `chrome120`)

## Troubleshooting

### `ERROR: /oidc/auth callback returned 403` (or 200 with HTML)

Imperva is blocking the callback — the Chrome TLS impersonation profile is
likely too old for current Imperva fingerprint rules. Try a newer profile:

```bash
.venv/bin/python manual_auth_debug.py --impersonate chrome124
```

Available profiles in `curl_cffi==0.7.4`: `chrome99`, `chrome100`,
`chrome101`, `chrome104`, `chrome107`, `chrome110`, `chrome116`,
`chrome119`, `chrome120`, `chrome123`, `chrome124`. List with:

```bash
.venv/bin/python -c "from curl_cffi import requests; print(list(requests.BrowserType))"
```

If the integration is hitting Imperva, set the same profile under
**Options → curl_cffi Chrome impersonation profile** in the HA UI.

### `ERROR: bad credentials`

Auth0 returns 200 with an inline error page when credentials are wrong.
Verify by logging into https://app.mobilelinkgen.com in a browser.

### Auth0 device drift

If logins start failing after weeks of success, delete
`~/.cache/generac-auto-login/cookies.json` and re-run — Auth0 may have
invalidated the persisted device identity.

## Regression-test commitment

Any PR that touches `custom_components/generac/auth.py` should run this
script against live Generac with `--verbose` and paste (redacted) output
into the PR description. Automated tests cover the pure helpers; the
in-script smoke test is the regression gate for the OIDC flow itself.
