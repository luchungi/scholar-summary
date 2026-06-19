import os
import base64
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import config

# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

def extract_links_from_html(html_content):
    """
    Parses Google Alert HTML content and extracts paper links.
    Filters out unsubscribe, edit, and other Google management links.
    """
    soup = BeautifulSoup(html_content, 'html.parser')
    links = []

    # We want to extract links that represent search results
    for a in soup.find_all('a', href=True):
        href = a['href']
        title = a.get_text(strip=True)

        parsed = urlparse(href)

        # If the link is to save the article in Google Scholar, it will have a query parameter "citations" so skip it
        # Similarly for social sharing links that have "scholar_share" in the path
        # Also skip links that have "q=" in the query, which are search result links
        if "citations" in parsed.path or "scholar_share" in parsed.path or "q=" in parsed.query:
            continue

        # Standardize/extract target URL from Google redirects
        if "google.com" in parsed.netloc and parsed.path == "/url":
            qs = parse_qs(parsed.query)
            target_url = qs.get("url", [None])[0]
            if target_url:
                href = target_url
                parsed = urlparse(href)

        # Filter out Google Alerts management links and general Google pages
        if "google.com" in parsed.netloc:
            # Skip google utility pages (alerts, support, accounts, search)
            if any(term in parsed.path or term in parsed.netloc for term in ["alerts", "support", "accounts", "policies", "preferences"]):
                continue

        # Skip internal, empty or mailto links
        if not href or href.startswith("mailto:") or href.startswith("#") or href.startswith("javascript:"):
            continue

        # Avoid duplicate URLs in the same email
        if not any(link["url"] == href for link in links):
            links.append({
                "title": title or "Untitled Resource",
                "url": href
            })

    return links

def get_html_body(part):
    """
    Recursively extracts the HTML body from a Gmail message part.
    """
    mime_type = part.get('mimeType')
    body = part.get('body', {})
    data = body.get('data')

    if mime_type == 'text/html' and data:
        return base64.urlsafe_b64decode(data.encode('ASCII')).decode('utf-8', errors='ignore')

    parts = part.get('parts', [])
    for subpart in parts:
        html = get_html_body(subpart)
        if html:
            return html

    return None

def fetch_latest_alerts(credentials_path=config.GMAIL_CREDENTIALS_PATH, token_path=config.GMAIL_TOKEN_PATH, limit=20):
    """
    Connects to Gmail via Google Gmail API, searches for Google Alert emails, and returns a list of alert items.
    """
    creds = None
    if os.path.exists(token_path):
        try:
            creds = Credentials.from_authorized_user_file(token_path, SCOPES)
        except Exception as e:
            print(f"Warning: Failed to load token file: {e}. Re-authenticating...")

    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Credentials expired. Refreshing token...")
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Warning: Failed to refresh token: {e}. Starting new auth flow...")
                flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
                creds = flow.run_local_server(port=0)
        else:
            print("No valid credentials found. Starting authentication flow...")
            flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(token_path, "w") as token:
            token.write(creds.to_json())

    print("Connecting to Gmail API...")
    try:
        service = build("gmail", "v1", credentials=creds)
    except Exception as e:
        raise ValueError(f"Failed to build Gmail service: {e}")

    print("Searching for Google Alert emails...")

    # list all emails in the user's primary inbox
    # existing_messages = []
    # try:
    #     results = service.users().messages().list(userId='me', labelIds=['INBOX'], maxResults=limit).execute()
    #     existing_messages = results.get('messages', [])
    #     print(results)
    # except HttpError as e:
    #     raise ValueError(f"Gmail API error listing messages: {e}")
    # print(f"Found {len(existing_messages)} total messages in inbox. Searching for Google Scholar Alerts...")
    # for msg_info in existing_messages:
    #     message = service.users().messages().get(
    #         userId='me',
    #         id=msg_info['id'],
    #         format='full' # Can be 'full', 'metadata', or 'minimal'
    #     ).execute()
    #     snippet = message.get('snippet', '')
    #     headers = message.get('payload', {}).get('headers', [])
    #     subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), '')
    #     sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), '')
    #     print(f"Message ID: {msg_info['id']}, Subject: {subject}, From: {sender}, Snippet: {snippet[:50]}...")


    # Try searching for scholaralerts-noreply@google.com first
    query = 'from:scholaralerts-noreply@google.com'
    try:
        results = service.users().messages().list(userId='me', labelIds=['INBOX'], q=query, maxResults=limit).execute()
        messages = results.get('messages', [])
    except HttpError as e:
        raise ValueError(f"Gmail API error searching emails: {e}")

    if not messages:
        print("No emails from scholaralerts-noreply@google.com found. Searching by Subject...")
        query = 'subject:"Google Scholar Alerts"'
        try:
            results = service.users().messages().list(userId='me', labelIds=['INBOX'], q=query, maxResults=limit).execute()
            messages = results.get('messages', [])
        except HttpError as e:
            raise ValueError(f"Gmail API error searching emails: {e}")

    if not messages:
        print("No Google Scholar Alerts emails found in inbox.")
        return []

    print(f"Found {len(messages)} Google Scholar Alerts emails. Fetching details...")
    alerts = []

    for msg_info in messages:
        msg_id = msg_info['id']
        try:
            msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
        except HttpError as e:
            print(f"Warning: Failed to fetch message {msg_id}: {e}")
            continue

        payload = msg.get('payload', {})
        headers = payload.get('headers', [])

        # Extract headers
        subject = "Google Scholar Alerts"
        date = ""
        for header in headers:
            name = header.get('name', '').lower()
            if name == 'subject':
                subject = header.get('value', 'Google Scholar Alerts')
            elif name == 'date':
                date = header.get('value', '')

        # Extract HTML body
        html_body = get_html_body(payload)

        if html_body:
            links = extract_links_from_html(html_body)
            alerts.append({
                "subject": subject,
                "date": date,
                "links": links
            })

    print(f"Retrieved {len(alerts)} alert email(s) containing a total of {sum(len(a['links']) for a in alerts)} unique links.")
    return alerts
