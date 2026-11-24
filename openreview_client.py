"""
Reads papers from the OpenReview API with the user's own account (decision 0023).

OpenReview answers guests with a bot challenge, on its site and on its API, and lets a
logged-in account through. The login lives only in config.OPENREVIEW_CREDENTIALS_PATH
(600, folder 700; written by scripts/setup_openreview.py) and is read only at login. The
token stays in memory. Neither is put in the environment, logs, results or error text, and
no request follows a redirect, so they can only reach the OpenReview API hosts.
"""
import os
import re
import stat
import threading
import time
from urllib.parse import parse_qs, urlparse

import requests

import config

API_V2 = "https://api2.openreview.net"
API_V1 = "https://api.openreview.net"  # legacy, still serves older venues
TOKEN_SECONDS = 3600
TOKEN_MARGIN_SECONDS = 60
REQUEST_TIMEOUT = 20
PDF_TIMEOUT = 60
MAX_CREDENTIALS_BYTES = 4096

_HOSTS = ("openreview.net", "www.openreview.net")
_NOTE_ID = re.compile(r"[A-Za-z0-9_-]+")
_SETUP_HINT = "run scripts/setup_openreview.py"

# Triage fetches papers in parallel, so the lock makes them share one login.
_lock = threading.Lock()
_token = None
_token_expires = 0.0
_login_failure = None  # set after a failed login, so a run cannot lock the account


class OpenReviewError(Exception):
    """A failure with text that is safe to show. It never holds a credential."""

    def __init__(self, reason, blocked=False):
        super().__init__(reason)
        self.reason = reason
        self.blocked = blocked


def extract_forum_id(url):
    """The note ID in an openreview.net /forum or /pdf link, or None."""
    try:
        parsed = urlparse(url or "")
        host = (parsed.hostname or "").lower()
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or host not in _HOSTS:
        return None
    if parsed.path.rstrip("/") not in ("/forum", "/pdf"):
        return None
    note_id = parse_qs(parsed.query).get("id", [""])[0]
    return note_id if _NOTE_ID.fullmatch(note_id) else None


def is_configured():
    return os.path.lexists(config.OPENREVIEW_CREDENTIALS_PATH)


def can_fetch(url):
    """True for an OpenReview paper link when a login is set up."""
    return bool(extract_forum_id(url)) and is_configured()


def reset_login_failure():
    """A new run or export may try the login again after an earlier one failed."""
    global _login_failure
    with _lock:
        _login_failure = None


def _load_credentials():
    """Reads the login from its private file, refusing a file others could read or replace."""
    path = config.OPENREVIEW_CREDENTIALS_PATH
    try:
        parent = os.lstat(os.path.dirname(path))
    except OSError:
        raise OpenReviewError(f"The OpenReview login file is missing; {_SETUP_HINT}") from None
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or parent.st_mode & 0o077:
        raise OpenReviewError("The OpenReview login folder must be a real folder only your user can access (mode 700)")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise OpenReviewError(f"The OpenReview login file could not be opened or is a symlink; {_SETUP_HINT}") from None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise OpenReviewError("The OpenReview login file must be a regular file only your user can read (mode 600)")
        if info.st_size > MAX_CREDENTIALS_BYTES:
            raise OpenReviewError(f"The OpenReview login file is not in the expected format; {_SETUP_HINT}")
        raw = os.read(descriptor, MAX_CREDENTIALS_BYTES + 1)
    finally:
        os.close(descriptor)

    values = {}
    try:
        for line in raw.decode("utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator:
                values[key] = value  # not stripped: a password may contain spaces
    except UnicodeDecodeError:
        values = {}
    email, password = values.get("OPENREVIEW_EMAIL"), values.get("OPENREVIEW_PASSWORD")
    if not email or not password:
        raise OpenReviewError(f"The OpenReview login file is not in the expected format; {_SETUP_HINT}")
    return email, password


def _error_name(response):
    try:
        body = response.json()
    except ValueError:
        return None
    return body.get("name") if isinstance(body, dict) else None


def _login():
    email, password = _load_credentials()
    network_error = None
    try:
        response = requests.post(
            f"{API_V2}/login",
            json={"id": email, "password": password, "expiresIn": TOKEN_SECONDS},
            allow_redirects=False,
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as e:
        # Only the type is kept: the exception's request object holds the password.
        network_error = type(e).__name__
    if network_error:
        raise OpenReviewError(f"Could not reach OpenReview to log in ({network_error})")

    status = response.status_code
    if status == 200:
        try:
            token = response.json().get("token")
        except (ValueError, AttributeError):
            token = None
        if not token:
            raise OpenReviewError("OpenReview login gave no token (is multi-factor login on?)")
        return token
    if status == 429:
        raise OpenReviewError("OpenReview rate-limited the login; try again later")
    if _error_name(response) == "ChallengeRequiredError":
        raise OpenReviewError("OpenReview's bot protection blocked the login", blocked=True)
    if status in (400, 401, 403):
        raise OpenReviewError(f"OpenReview login failed; check the email and password ({_SETUP_HINT})")
    raise OpenReviewError(f"OpenReview login returned HTTP {status}")


def _get_token(stale=None):
    """The current token, logging in if needed. `stale` is a token the API just refused."""
    global _token, _token_expires, _login_failure
    with _lock:
        if stale is not None and _token == stale:
            _token = None
        if _login_failure:
            raise OpenReviewError(*_login_failure)
        if _token and time.monotonic() < _token_expires - TOKEN_MARGIN_SECONDS:
            return _token
        try:
            _token = _login()
        except OpenReviewError as e:
            _token = None
            _login_failure = (e.reason, e.blocked)
            raise
        _token_expires = time.monotonic() + TOKEN_SECONDS
        return _token


def _send(base, path, note_id, token, timeout):
    network_error = None
    try:
        return requests.get(
            f"{base}{path}",
            params={"id": note_id},
            headers={"Cookie": f"openreview.accessToken={token}"},
            allow_redirects=False,
            timeout=timeout,
        )
    except requests.RequestException as e:
        # Only the type is kept: the exception's request object holds the token.
        network_error = type(e).__name__
    raise OpenReviewError(f"Could not reach OpenReview ({network_error})")


def _get(base, path, note_id, timeout=REQUEST_TIMEOUT):
    """GETs with the token. An expired token gets one fresh login and one more try."""
    token = _get_token()
    response = _send(base, path, note_id, token, timeout)
    if response.status_code == 401:
        response = _send(base, path, note_id, _get_token(stale=token), timeout)
    return response


def _raise_for(response):
    status = response.status_code
    if status == 429:
        raise OpenReviewError("OpenReview's rate limit was reached; try again later")
    if status == 403 and _error_name(response) == "ChallengeRequiredError":
        raise OpenReviewError("Blocked by OpenReview's bot protection even when logged in", blocked=True)
    if status == 403:
        raise OpenReviewError("OpenReview says this paper is not public to your account")
    if status == 401:
        raise OpenReviewError("OpenReview refused the login token")
    raise OpenReviewError(f"OpenReview returned HTTP {status}")


def _find_note(note_id):
    """Finds the note on API V2, then V1. Returns (base URL, note)."""
    for base in (API_V2, API_V1):
        response = _get(base, "/notes", note_id)
        if response.status_code == 404:
            continue
        if response.status_code != 200:
            _raise_for(response)
        try:
            notes = response.json().get("notes") or []
        except (ValueError, AttributeError):
            raise OpenReviewError("OpenReview sent an unreadable answer") from None
        if notes:
            return base, notes[0]
    raise OpenReviewError("OpenReview has no paper with this ID")


def _field(content, name):
    """A note's field: V2 wraps each value as {"value": ...}, V1 does not."""
    value = content.get(name)
    if isinstance(value, dict):
        value = value.get("value")
    return value if isinstance(value, str) and value.strip() else None


def fetch_paper(url):
    """
    Fetches a paper by its openreview.net link. Returns None when this does not apply (not
    an OpenReview link, or no login set up). Otherwise a dict with "pdf" (bytes or None),
    "title", "abstract", "reason" (why there is no PDF) and "blocked".
    """
    if not can_fetch(url):
        return None
    note_id = extract_forum_id(url)

    result ={"pdf": None, "title": None, "abstract": None, "reason": None, "blocked": False}
    try:
        base, note = _find_note(note_id)
        content = note.get("content") or {}
        result["title"] = _field(content, "title")
        result["abstract"] = _field(content, "abstract")
        if not _field(content, "pdf"):
            result["reason"] = "OpenReview lists no PDF for this paper"
            return result
        response = _get(base, "/pdf", note_id, PDF_TIMEOUT)
        if response.status_code == 404:
            result["reason"] = "OpenReview has no PDF file for this paper"
        elif response.status_code != 200:
            _raise_for(response)
        else:
            result["pdf"] = response.content
    except OpenReviewError as e:
        result["reason"] = e.reason
        result["blocked"] = e.blocked
    return result
