# 0023: OpenReview papers come through its API with the user's account

- Status: Accepted
- Date: 2026-11-24
- Context: Run 157 failed paper 446, and 7 OpenReview papers were stuck as failed. Logged-out
  requests get HTTP 403 ChallengeRequiredError on the site and on both API versions; the API
  spec calls it a guest-scraping challenge. A logged-in request passes: notes and PDF answered
  200 on V2, and on V1 with the same token. This narrows 0019's finding on OpenReview. 0019's
  rule against getting around bot checks stands; the documented API with the user's own
  account does not get around one.
- Decisions:
  1. For openreview.net /forum and /pdf links: user PDF, then the API, then the arXiv title
     match, then a recorded reason. With a login the site and academic APIs are skipped.
     Without the login file, behaviour is unchanged.
  2. A small `requests` client (openreview_client.py): POST /login, GET /notes, GET /pdf,
     trying V2 and, on 404, V1.
  3. The login lives only in ~/.config/scholar-summary/openreview.env (600, folder 700),
     written by scripts/setup_openreview.py with hidden input and read only at login. Never
     in Keychain, .env, the environment, logs, results or error text.
  4. A one-hour token stays in memory, shared by parallel triage. No request follows a
     redirect. A 401 gets one fresh login.
  5. A failed login stops further attempts until the next run or export, to avoid a lockout.
     Rate limits and API errors are not retried.
  6. It takes the PDF, title and abstract. Without a PDF the abstract still feeds the gate (0018).
  7. Single-PDF and EndNote exports fetch through the same client. Their link holds no secret.
- Alternatives considered:
  - macOS Keychain: per-item access protects other items, but the item would trust the shared,
    ad-hoc-signed uv Python, and updates would bring back prompts. Apple's per-app keychain
    needs a provisioning profile. The user wants no route into Keychain (0022).
  - Project .env: mode 644, inside the repo, and its values reach child processes.
  - openreview-py: adds a dependency tree to the process holding the password, for three calls.
  - arXiv before the API: may review a different version from the one in the alert.
  - API only: loses the arXiv copy when the login or API is down.
  - EndNote metadata from the API: useful, but beyond fixing retrieval.
- Consequences: T-050..T-052. The password is plain text at rest, readable by anything running
  as the user and possibly in backups, so it must be unique to OpenReview. The terms do not
  address scripted logins directly; the docs show scripts logging in with a password.
- Revisit if: logged-in requests get challenged, OpenReview offers API keys, or its terms
  restrict scripted access.
