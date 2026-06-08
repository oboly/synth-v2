from __future__ import annotations

import re
import subprocess
from pathlib import Path

# Sources under test
INSTALLER = Path("scripts/odroid/activate_nginx_transition_dual_auth_v1.sh").read_text(encoding="utf-8")
CONF_TRANSITION = Path("docs/deployment/nginx_transition_dual_auth_v1.conf").read_text(encoding="utf-8")
CONF_TEMPLATE = Path("docs/deployment/nginx_auth_request_template_v1.conf").read_text(encoding="utf-8")

SOURCES = {
    "installer": INSTALLER,
    "transition_conf": CONF_TRANSITION,
    "template_conf": CONF_TEMPLATE,
}

NAMED_CAPTURE_PATTERN = r'(?<synth_profile_slug>[a-z0-9][a-z0-9_-]{0,62})'
NUMERIC_SET_PATTERN = r'set \$synth_profile_slug \$1'


# -- Bash syntax --

def test_installer_bash_syntax_valid() -> None:
    result = subprocess.run(
        ["bash", "-n", "scripts/odroid/activate_nginx_transition_dual_auth_v1.sh"],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode()


# -- Named capture present, numeric capture absent --

def test_installer_uses_named_capture() -> None:
    assert NAMED_CAPTURE_PATTERN in INSTALLER, (
        "activate_nginx_transition_dual_auth_v1.sh must use named capture (?<synth_profile_slug>...)"
    )


def test_transition_conf_uses_named_capture() -> None:
    assert NAMED_CAPTURE_PATTERN in CONF_TRANSITION, (
        "nginx_transition_dual_auth_v1.conf must use named capture (?<synth_profile_slug>...)"
    )


def test_template_conf_uses_named_capture() -> None:
    assert NAMED_CAPTURE_PATTERN in CONF_TEMPLATE, (
        "nginx_auth_request_template_v1.conf must use named capture (?<synth_profile_slug>...)"
    )


def test_installer_has_no_numeric_set_line() -> None:
    assert NUMERIC_SET_PATTERN not in INSTALLER, (
        "activate_nginx_transition_dual_auth_v1.sh must not use 'set $synth_profile_slug $1'"
    )


def test_transition_conf_has_no_numeric_set_line() -> None:
    assert NUMERIC_SET_PATTERN not in CONF_TRANSITION, (
        "nginx_transition_dual_auth_v1.conf must not use 'set $synth_profile_slug $1'"
    )


def test_template_conf_has_no_numeric_set_line() -> None:
    assert NUMERIC_SET_PATTERN not in CONF_TEMPLATE, (
        "nginx_auth_request_template_v1.conf must not use 'set $synth_profile_slug $1'"
    )


# -- Named capture regex correctness --

def _location_regex(source: str) -> str | None:
    """Extract the nginx location ~ regex string from the source."""
    m = re.search(r'location\s*~\s*"([^"]+)"', source)
    return m.group(1) if m else None


def _nginx_regex_to_python(pattern: str) -> str:
    """Convert nginx named-capture syntax to Python re syntax."""
    return pattern.replace("(?<", "(?P<")


def _match_profile_path(location_pattern: str, path: str) -> re.Match | None:
    py_pattern = _nginx_regex_to_python(location_pattern)
    return re.match(py_pattern, path)


def _get_profile(location_pattern: str, path: str) -> str | None:
    m = _match_profile_path(location_pattern, path)
    if m is None:
        return None
    try:
        return m.group("synth_profile_slug")
    except IndexError:
        return None


# Test with the installer pattern (all three files share the same regex).
_INSTALLER_LOCATION_RE = _location_regex(INSTALLER) or ""


def test_named_capture_matches_profile_home() -> None:
    slug = _get_profile(_INSTALLER_LOCATION_RE, "/synth/accounts/joost")
    assert slug == "joost"


def test_named_capture_matches_wallet_html() -> None:
    slug = _get_profile(_INSTALLER_LOCATION_RE, "/synth/accounts/joost/wallet.html")
    assert slug == "joost"


def test_named_capture_matches_profit_plan_html() -> None:
    slug = _get_profile(_INSTALLER_LOCATION_RE, "/synth/accounts/joost/profit-plan.html")
    assert slug == "joost"


def test_named_capture_matches_open_orders_monitor() -> None:
    slug = _get_profile(_INSTALLER_LOCATION_RE, "/synth/accounts/joost/open-orders-monitor.html")
    assert slug == "joost"


def test_named_capture_matches_nested_runtime_path() -> None:
    slug = _get_profile(
        _INSTALLER_LOCATION_RE,
        "/synth/accounts/joost/_runtime/native_short_context_v1/native_short_fib_context_rows_v1.csv",
    )
    assert slug == "joost"


def test_named_capture_exact_profile_slug_on_nested_path() -> None:
    slug = _get_profile(_INSTALLER_LOCATION_RE, "/synth/accounts/alpha-user/profit-plan.html")
    assert slug == "alpha-user"


def test_cross_profile_path_does_not_bleed_slug() -> None:
    """The profile slug captured must be the one in the URI, not a neighbour."""
    slug_alpha = _get_profile(_INSTALLER_LOCATION_RE, "/synth/accounts/alpha/wallet.html")
    slug_beta = _get_profile(_INSTALLER_LOCATION_RE, "/synth/accounts/beta/wallet.html")
    assert slug_alpha == "alpha"
    assert slug_beta == "beta"
    assert slug_alpha != slug_beta


def test_non_account_path_does_not_match() -> None:
    m = _match_profile_path(_INSTALLER_LOCATION_RE, "/synth/entry-candidates.html")
    assert m is None


def test_path_traversal_does_not_match() -> None:
    m = _match_profile_path(_INSTALLER_LOCATION_RE, "/synth/accounts/../etc/passwd")
    assert m is None


def test_numeric_profile_slug_is_valid() -> None:
    """Slug may start with a digit."""
    slug = _get_profile(_INSTALLER_LOCATION_RE, "/synth/accounts/42user/wallet.html")
    assert slug == "42user"


# -- Basic Auth must remain enabled --

def test_installer_basic_auth_still_present() -> None:
    assert "auth_basic" in INSTALLER


def test_transition_conf_basic_auth_still_present() -> None:
    assert "auth_basic" in CONF_TRANSITION


# -- Auth request still wired --

def test_installer_auth_request_still_wired() -> None:
    assert "auth_request" in INSTALLER


def test_transition_conf_auth_request_still_wired() -> None:
    assert "auth_request" in CONF_TRANSITION


# -- Proxy header still forwarded --

def test_installer_proxy_header_still_set() -> None:
    assert "X-Synth-Requested-Profile" in INSTALLER
    assert "$synth_profile_slug" in INSTALLER


def test_transition_conf_proxy_header_still_set() -> None:
    assert "X-Synth-Requested-Profile" in CONF_TRANSITION
    assert "$synth_profile_slug" in CONF_TRANSITION
