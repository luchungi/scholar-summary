from __future__ import annotations

import imaplib
import json
import os
import re
import urllib.request
from dataclasses import dataclass
from email import message_from_bytes
from email.header import decode_header, make_header
from email.message import Message
from typing import Protocol, Sequence


@dataclass(frozen=True)
class ScholarAlertEmail:
    subject: str
    sender: str
    body: str


@dataclass(frozen=True)
class PaperCandidate:
    title: str
    url: str


@dataclass(frozen=True)
class PaperAnalysis:
    title: str
    url: str
    key_ideas: str
    literature_context: str
    contribution: str
    interest_fit: str


class ScholarAlertSource(Protocol):
    def fetch_google_scholar_alerts(self, limit: int = 20) -> list[ScholarAlertEmail]:
        ...


class PaperAnalyzer(Protocol):
    def analyze_paper(
        self,
        paper: PaperCandidate,
        user_interest_prompts: Sequence[str],
    ) -> PaperAnalysis:
        ...


class GmailIMAPScholarAlertSource:
    """Fetch Google Scholar alert emails from a Gmail account via IMAP."""

    def __init__(self, username: str, password: str, imap_host: str = "imap.gmail.com") -> None:
        self.username = username
        self.password = password
        self.imap_host = imap_host

    def fetch_google_scholar_alerts(self, limit: int = 20) -> list[ScholarAlertEmail]:
        with imaplib.IMAP4_SSL(self.imap_host) as client:
            client.login(self.username, self.password)
            client.select("INBOX")
            status, data = client.search(None, '(FROM "scholaralerts-noreply@google.com")')
            if status != "OK" or not data:
                return []

            ids = data[0].split()
            recent_ids = ids[-limit:]
            emails: list[ScholarAlertEmail] = []
            for email_id in reversed(recent_ids):
                fetch_status, message_data = client.fetch(email_id, "(RFC822)")
                if fetch_status != "OK" or not message_data:
                    continue

                payload = next((part for part in message_data if isinstance(part, tuple)), None)
                if not payload:
                    continue

                msg = message_from_bytes(payload[1])
                subject = _decode_header(msg.get("Subject", ""))
                sender = _decode_header(msg.get("From", ""))
                body = _extract_text_body(msg)
                email_item = ScholarAlertEmail(subject=subject, sender=sender, body=body)
                if is_google_scholar_alert(email_item):
                    emails.append(email_item)
            return emails


class LocalLLMPaperAnalyzer:
    """Use a local chat-completions endpoint to analyze papers."""

    def __init__(
        self,
        endpoint: str = "http://localhost:11434/v1/chat/completions",
        model: str = "llama3.1",
        timeout: int = 120,
    ) -> None:
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout

    def analyze_paper(
        self,
        paper: PaperCandidate,
        user_interest_prompts: Sequence[str],
    ) -> PaperAnalysis:
        prompt = (
            "You are analyzing a newly alerted research paper.\n"
            f"Paper title: {paper.title}\n"
            f"Candidate URL: {paper.url}\n"
            "User interests:\n"
            + "\n".join(f"- {i}" for i in user_interest_prompts)
            + "\n\n"
            "Find the paper from the title/URL context and return strict JSON with keys: "
            "key_ideas, literature_context, contribution, interest_fit."
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a research assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }

        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            response_data = json.loads(response.read().decode("utf-8"))

        content = response_data["choices"][0]["message"]["content"]
        parsed = _parse_json_from_response(content)

        return PaperAnalysis(
            title=paper.title,
            url=paper.url,
            key_ideas=parsed.get("key_ideas", ""),
            literature_context=parsed.get("literature_context", ""),
            contribution=parsed.get("contribution", ""),
            interest_fit=parsed.get("interest_fit", ""),
        )


class ScholarSummaryAgent:
    def __init__(self, source: ScholarAlertSource, analyzer: PaperAnalyzer) -> None:
        self.source = source
        self.analyzer = analyzer

    def run(self, user_interest_prompts: Sequence[str], limit: int = 20) -> str:
        alerts = self.source.fetch_google_scholar_alerts(limit=limit)
        papers: list[PaperCandidate] = []
        for alert in alerts:
            papers.extend(extract_paper_candidates(alert))

        deduped = _dedupe_papers(papers)
        analyses = [self.analyzer.analyze_paper(paper, user_interest_prompts) for paper in deduped]
        return format_report(analyses, user_interest_prompts)


def is_google_scholar_alert(email_item: ScholarAlertEmail) -> bool:
    sender = email_item.sender.lower()
    subject = email_item.subject.lower()
    return "scholaralerts-noreply@google.com" in sender or "google scholar" in subject


def extract_paper_candidates(email_item: ScholarAlertEmail) -> list[PaperCandidate]:
    body = email_item.body
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    candidates: list[PaperCandidate] = []

    for idx, line in enumerate(lines):
        if line.startswith("http://") or line.startswith("https://"):
            title = lines[idx - 1] if idx > 0 else _title_from_url(line)
            candidates.append(PaperCandidate(title=title, url=line))

    markdown_links = re.findall(r"\[([^\]]+)\]\((https?://[^\)]+)\)", body)
    for title, url in markdown_links:
        candidates.append(PaperCandidate(title=title.strip(), url=url.strip()))

    return _dedupe_papers(candidates)


def format_report(analyses: Sequence[PaperAnalysis], user_interest_prompts: Sequence[str]) -> str:
    if not analyses:
        return "# Scholar Alert Report\n\nNo Google Scholar alert papers were found."

    parts = ["# Scholar Alert Report", "", "## User interests", ""]
    parts.extend(f"- {item}" for item in user_interest_prompts)
    parts.append("")

    for idx, analysis in enumerate(analyses, start=1):
        parts.extend(
            [
                f"## Paper {idx}: {analysis.title}",
                f"Source: {analysis.url}",
                "",
                "### 1) High-level key ideas",
                analysis.key_ideas,
                "",
                "### 2) Link to literature and contribution",
                f"Literature links: {analysis.literature_context}",
                f"Contribution: {analysis.contribution}",
                "",
                "### 3) Fit with user interests",
                analysis.interest_fit,
                "",
            ]
        )

    return "\n".join(parts).strip() + "\n"


def build_agent_from_env() -> ScholarSummaryAgent:
    username = os.environ.get("GMAIL_USERNAME")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    endpoint = os.environ.get("LOCAL_LLM_ENDPOINT", "http://localhost:11434/v1/chat/completions")
    model = os.environ.get("LOCAL_LLM_MODEL", "llama3.1")

    if not username or not password:
        raise ValueError("GMAIL_USERNAME and GMAIL_APP_PASSWORD must be set")

    source = GmailIMAPScholarAlertSource(username, password)
    analyzer = LocalLLMPaperAnalyzer(endpoint=endpoint, model=model)
    return ScholarSummaryAgent(source=source, analyzer=analyzer)


def _decode_header(value: str) -> str:
    return str(make_header(decode_header(value)))


def _extract_text_body(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                payload = part.get_payload(decode=True)
                if payload is not None:
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/html":
                payload = part.get_payload(decode=True)
                if payload is not None:
                    html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                    return re.sub(r"<[^>]+>", " ", html)
    payload = msg.get_payload(decode=True)
    if payload is None:
        return ""
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")


def _title_from_url(url: str) -> str:
    token = url.rstrip("/").split("/")[-1]
    cleaned = re.sub(r"[-_]+", " ", token)
    return cleaned or "Untitled paper"


def _dedupe_papers(papers: Sequence[PaperCandidate]) -> list[PaperCandidate]:
    seen: set[str] = set()
    deduped: list[PaperCandidate] = []
    for paper in papers:
        key = paper.url.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(paper)
    return deduped


def _parse_json_from_response(content: str) -> dict[str, str]:
    content = content.strip()
    if not content:
        return {}

    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?", "", content).strip()
        content = re.sub(r"```$", "", content).strip()

    try:
        loaded = json.loads(content)
        if isinstance(loaded, dict):
            return {str(k): str(v) for k, v in loaded.items()}
    except json.JSONDecodeError:
        pass

    return {"key_ideas": content, "literature_context": "", "contribution": "", "interest_fit": ""}


def main() -> int:
    prompts_env = os.environ.get("USER_INTEREST_PROMPTS", "")
    prompts = [item.strip() for item in prompts_env.split("||") if item.strip()]
    if not prompts:
        raise ValueError("Set USER_INTEREST_PROMPTS as 'topic 1||topic 2'")

    agent = build_agent_from_env()
    report = agent.run(prompts)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
