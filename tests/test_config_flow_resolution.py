"""Unit tests for the gesture-matrix resolution helper in config_flow.py."""
from __future__ import annotations

import pytest

from custom_components.generac import config_flow as cf


# Shorthand for empty/sentinel
EMPTY = ""


def _form(email: str = EMPTY, password: str = EMPTY, cookie: str = EMPTY) -> dict:
    return {"email": email, "auth_password": password, "session_cookie": cookie}


def _auto_mint_stored() -> dict:
    return {
        "email": "user@example.com",
        "auth_password": "stored-pw",
        "session_cookie": "MobileLinkClientCookie=old",
        "device_cookies": {"did": {"value": "x", "domain": ".auth.ecobee.com"}},
        "cookie_minted_at": 1000000.0,
    }


def _paste_only_stored() -> dict:
    return {"session_cookie": "MobileLinkClientCookie=old"}


class TestResolveMode:
    # Row 1: AUTO_MINT stored, email unchanged, blank password → reuse stored pw
    def test_auto_mint_unchanged_blank_password_reuses_stored(self) -> None:
        result = cf._resolve_mode(
            form=_form(email="user@example.com", password="", cookie="MobileLinkClientCookie=old"),
            stored=_auto_mint_stored(),
        )
        assert result.mode == "AUTO_MINT"
        assert result.effective_password == "stored-pw"
        assert result.error_key is None

    # Row 2: AUTO_MINT stored, email unchanged, new password → use new pw
    def test_auto_mint_unchanged_new_password_uses_new(self) -> None:
        result = cf._resolve_mode(
            form=_form(email="user@example.com", password="new-pw", cookie="MobileLinkClientCookie=old"),
            stored=_auto_mint_stored(),
        )
        assert result.mode == "AUTO_MINT"
        assert result.effective_password == "new-pw"
        assert result.error_key is None

    # Row 3: AUTO_MINT stored, email cleared, cookie unchanged → switch to PASTE_ONLY
    def test_clearing_email_switches_to_paste_only(self) -> None:
        result = cf._resolve_mode(
            form=_form(email="", password="", cookie="MobileLinkClientCookie=old"),
            stored=_auto_mint_stored(),
        )
        assert result.mode == "PASTE_ONLY"
        assert result.error_key is None
        assert set(result.deletions) == {
            "email", "auth_password", "device_cookies", "cookie_minted_at",
        }

    # Row 4: AUTO_MINT stored, email cleared, cookie cleared → form error
    def test_clearing_both_email_and_cookie_errors(self) -> None:
        result = cf._resolve_mode(
            form=_form(email="", password="", cookie=""),
            stored=_auto_mint_stored(),
        )
        assert result.mode is None
        assert result.error_key == "need_creds_or_cookie"

    # Row 5: AUTO_MINT stored, email changed, blank password → form error
    def test_changing_email_without_password_errors(self) -> None:
        result = cf._resolve_mode(
            form=_form(email="other@example.com", password="", cookie="MobileLinkClientCookie=old"),
            stored=_auto_mint_stored(),
        )
        assert result.mode is None
        assert result.error_key == "password_required_for_email"

    # Row 6: AUTO_MINT stored, email changed, new password → AUTO_MINT, wipe device cookies
    def test_changing_email_with_new_password_wipes_device_cookies(self) -> None:
        result = cf._resolve_mode(
            form=_form(email="other@example.com", password="new-pw", cookie=""),
            stored=_auto_mint_stored(),
        )
        assert result.mode == "AUTO_MINT"
        assert result.effective_password == "new-pw"
        assert "device_cookies" in result.deletions

    # Row 7: PASTE_ONLY stored, just a new cookie → stay PASTE_ONLY
    def test_paste_only_new_cookie_stays_paste_only(self) -> None:
        result = cf._resolve_mode(
            form=_form(email="", password="", cookie="MobileLinkClientCookie=NEW"),
            stored=_paste_only_stored(),
        )
        assert result.mode == "PASTE_ONLY"
        assert result.error_key is None
        assert result.deletions == []

    # Row 8: PASTE_ONLY stored, enabling AUTO_MINT
    def test_paste_only_switching_to_auto_mint(self) -> None:
        result = cf._resolve_mode(
            form=_form(email="user@example.com", password="pw", cookie=""),
            stored=_paste_only_stored(),
        )
        assert result.mode == "AUTO_MINT"
        assert result.effective_password == "pw"
        assert result.error_key is None

    # Row 9: AUTO_MINT stored — HA's UI re-sent the email default even
    # though user "cleared" it, but user pasted a NEW cookie + no
    # password → must switch to PASTE_ONLY and wipe stored creds.
    # Real-world repro for the "Auth flow failed" stuck state.
    def test_new_cookie_with_no_password_switches_to_paste_only(self) -> None:
        result = cf._resolve_mode(
            form=_form(
                email="user@example.com",   # stale form default
                password="",
                cookie="MobileLinkClientCookie=FRESH-MANUAL-PASTE",
            ),
            stored=_auto_mint_stored(),
        )
        assert result.mode == "PASTE_ONLY"
        assert result.effective_password is None
        assert result.error_key is None
        assert set(result.deletions) == {
            "email", "auth_password", "device_cookies", "cookie_minted_at",
        }

    # Row 10: AUTO_MINT stored, user resubmits form unchanged → stay
    # AUTO_MINT (don't accidentally trip the new revert gesture).
    def test_unchanged_form_resubmit_stays_auto_mint(self) -> None:
        result = cf._resolve_mode(
            form=_form(
                email="user@example.com",
                password="",
                cookie="MobileLinkClientCookie=old",   # same as stored
            ),
            stored=_auto_mint_stored(),
        )
        assert result.mode == "AUTO_MINT"
        assert result.effective_password == "stored-pw"
        assert result.error_key is None

    # Row 11: AUTO_MINT stored, user rotates cookie manually AND fills
    # password → stay AUTO_MINT (password presence is the AUTO_MINT
    # signal; new cookie alone is the PASTE_ONLY signal).
    def test_new_cookie_with_password_stays_auto_mint(self) -> None:
        result = cf._resolve_mode(
            form=_form(
                email="user@example.com",
                password="new-pw",
                cookie="MobileLinkClientCookie=manual-override",
            ),
            stored=_auto_mint_stored(),
        )
        assert result.mode == "AUTO_MINT"
        assert result.effective_password == "new-pw"
        assert result.error_key is None
