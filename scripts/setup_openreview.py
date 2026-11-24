"""
Stores the OpenReview login in a private file outside the repository.

Run it in your own terminal, once on each Mac:

    .venv/bin/python scripts/setup_openreview.py

The password is typed with hidden input. The file is readable by your user only, and this
script never prints the password or sends it anywhere.
"""
import getpass
import os
import stat
import sys
import tempfile
import warnings
from pathlib import Path

CREDENTIALS_PATH = Path.home() / ".config" / "scholar-summary" / "openreview.env"


def validate(email, password):
    """Returns what is wrong with the login, or None. Never includes the values."""
    if not email or "@" not in email or any(c.isspace() for c in email):
        return "The email address is not valid."
    if not password:
        return "The password is empty."
    if "\n" in password or "\r" in password:
        return "The password cannot contain a line break."
    return None


def _prepare_directory(directory):
    """Creates the directory if needed and makes it private to this user."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"{directory} is a symlink or not a directory.")
    if info.st_uid != os.getuid():
        raise ValueError(f"{directory} belongs to another user.")
    os.chmod(directory, 0o700)


def write_credentials(path, email, password):
    """Writes the login atomically, so a failed write cannot leave a partial file."""
    problem = validate(email, password)
    if problem:
        raise ValueError(problem)
    _prepare_directory(path.parent)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError(f"{path} is a symlink or not a regular file.")

    # mkstemp creates the file with owner-only permissions (0600).
    descriptor, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".openreview-", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as f:
            f.write(f"OPENREVIEW_EMAIL={email}\nOPENREVIEW_PASSWORD={password}\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def _read_hidden(prompt):
    # getpass falls back to visible input with only a warning, so that warning is an error here.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass(prompt)


def main():
    if not sys.stdin.isatty():
        print("Run this in an interactive terminal, so the password can be typed with hidden input.")
        return 1
    try:
        if CREDENTIALS_PATH.exists() or CREDENTIALS_PATH.is_symlink():
            answer = input(f"{CREDENTIALS_PATH} already exists. Replace it? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                print("Left it unchanged.")
                return 0

        email = input("OpenReview email: ").strip()
        password = _read_hidden("OpenReview password (hidden): ")
        if password != _read_hidden("Repeat the password (hidden): "):
            print("The passwords did not match. Nothing was saved.")
            return 1
        write_credentials(CREDENTIALS_PATH, email, password)
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled. Nothing was saved.")
        return 1
    except (ValueError, OSError, getpass.GetPassWarning) as e:
        print(f"Nothing was saved: {e}")
        return 1

    print(f"Saved to {CREDENTIALS_PATH} (readable by your user only).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
