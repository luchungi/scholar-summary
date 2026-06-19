import os
import re
import sys
import argparse
import difflib
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import config
import gmail_fetcher
import paper_retriever
import agent

def ensure_interests_file():
    """
    Ensures that the user interests file exists, creating a default one if necessary.
    """
    filepath = Path(config.INTERESTS_FILE)
    if not filepath.exists():
        print(f"Interests file '{config.INTERESTS_FILE}' not found. Creating a default one...")
        default_content = """# User Research Interests

## Primary Areas of Interest

*   **AI Agents**: Autonomous agents, multi-agent collaboration, tool use, planning, and agentic workflows.
*   **Large Language Models (LLMs)**: Retrieval-augmented generation (RAG), context window expansion, prompt engineering, and local LLM deployment.
*   **Software Engineering Automation**: Code generation, automated debugging, and agentic coding assistants.

## Secondary Areas of Interest

*   **Biomedical NLP**: Clinical applications of natural language processing and medical database integration.
*   **Workflow Automation**: Automated scientific literature search, document summarization, and knowledge management.

## Specific Keywords

`LLM routing`, `function calling`, `aisuite`, `langchain`, `semantic search`, `vector databases`, `small language models (SLMs)`.
"""
        filepath.write_text(default_content, encoding="utf-8")
    return filepath.read_text(encoding="utf-8")

def sanitize_filename(name):
    """
    Sanitizes a string to be safe for filenames.
    """
    sanitized = re.sub(r'[^\w\s-]', '', name)
    sanitized = re.sub(r'[-\s]+', '_', sanitized)
    return sanitized.strip("_").lower()[:50]

def print_diff(old_text, new_text):
    """
    Computes and prints a git-like colored diff between old_text and new_text.
    """
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile="user_interests.md (current)",
        tofile="user_interests.md (updated)",
        n=3
    )

    has_diff = False
    for line in diff:
        has_diff = True
        if line.startswith('+') and not line.startswith('+++'):
            # Green text
            print(f"\033[92m{line}\033[0m", end="")
        elif line.startswith('-') and not line.startswith('---'):
            # Red text
            print(f"\033[91m{line}\033[0m", end="")
        elif line.startswith('@@'):
            # Cyan text
            print(f"\033[96m{line}\033[0m", end="")
        else:
            print(line, end="")

    if not has_diff:
        print("No changes detected in interest profile.")
    return has_diff

def process_single_paper(title, url):
    """
    Processes a single paper URL: downloads it, generates report, prompts for feedback, and updates profile.
    """
    print("=" * 60)
    print(f"Processing Paper: {title}")
    print(f"URL: {url}")
    print("=" * 60)

    # 1. Load interests
    current_interests = ensure_interests_file()

    # 2. Retrieve paper text
    paper_text = paper_retriever.retrieve_paper_text(url)
    if not paper_text:
        print("[-] Skipping paper: could not retrieve text.")
        return False

    print(f"[+] Retrieved {len(paper_text)} characters of text.")

    # 3. Generate report using local LLM
    try:
        report = agent.generate_paper_report(title, url, paper_text, current_interests)
    except ConnectionError as e:
        print(f"\n[!] Connection Error: {e}")
        print("Please start your local LLM server in LM Studio and try again.")
        return True

    # add title and link to the top of the report
    report = f"# {title}\n\n**Link**: {url}\n\n---\n\n" + report

    # 4. Save report
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    safe_title = sanitize_filename(title)
    report_path = Path(config.REPORTS_DIR) / f"report_{safe_title}.md"
    report_path.write_text(report, encoding="utf-8")

    print("\n" + "=" * 20 + " GENERATED REPORT " + "=" * 20)
    print(report)
    print("=" * 58)
    print(f"[+] Report saved to {report_path}")

    return True

def feedback_process():
    """
    Prompts the user for feedback on the generated reports and updates the interest profile accordingly.
    """

    print("\n" + "-" * 60)
    feedback = input("Provide feedback on the reports to update your Interest Profile (press Enter to skip): ").strip()

    # Load interests
    current_interests = ensure_interests_file()


    if feedback:
        print("[+] Processing feedback and updating profile...")
        try:
            updated_interests = agent.update_user_interests(current_interests, feedback)

            print("\n--- Proposed Interest Profile Changes ---")
            has_changes = print_diff(current_interests, updated_interests)

            if has_changes:
                confirm = input("\nSave these changes to your user_interests.md profile? (y/n): ").strip().lower()
                if confirm == 'y':
                    Path(config.INTERESTS_FILE).write_text(updated_interests, encoding="utf-8")
                    print("[+] Profile updated successfully!")
                else:
                    print("[-] Changes discarded.")
        except ConnectionError as e:
            print(f"[!] Error updating profile: {e}")
    else:
        print("[-] Feedback skipped. Profile unchanged.")

def normalize_url(url):
    """
    Normalizes a URL by resolving Google Scholar and Google redirect parameters
    to get the clean target URL.
    """
    try:
        parsed = urlparse(url)
        if "google.com" in parsed.netloc and parsed.path in ("/url", "/scholar_url"):
            qs = parse_qs(parsed.query)
            target_url = qs.get("url", [None])[0]
            if target_url:
                return target_url.strip()
    except Exception:
        pass
    return url.strip()

def remove_duplicate_links(alerts):
    """
    Removes duplicated links across the entire alerts object.
    A link is considered a duplicate if both the title and the normalized URL are the same.
    Keeps the first appearance of the link (newest alert email first).
    """
    seen_links = set()
    deduplicated_alerts = []

    for alert in alerts:
        new_links = []
        for link in alert.get("links", []):
            title = link.get("title", "").strip()
            url = link.get("url", "").strip()

            norm_url = normalize_url(url)
            identifier = (title, norm_url)

            if identifier not in seen_links:
                seen_links.add(identifier)
                new_links.append({
                    "title": title,
                    "url": norm_url
                })

        new_alert = {**alert, "links": new_links}
        deduplicated_alerts.append(new_alert)

    print(f"[+] Deduplicated links across alerts. Total unique links: {len(seen_links)}")

    return deduplicated_alerts

def run_gmail_flow(failed_papers=None):
    """
    Connects to Gmail, pulls latest alerts, and prompts user to process them.
    """
    if failed_papers is None:
        failed_papers = []
    try:
        config.validate_config()
    except ValueError as e:
        print(f"\n[!] Configuration Error:\n{e}")
        return

    try:
        alerts = gmail_fetcher.fetch_latest_alerts(
            credentials_path=config.GMAIL_CREDENTIALS_PATH,
            token_path=config.GMAIL_TOKEN_PATH,
            limit=config.MAX_EMAIL_FETCH
        )
    except Exception as e:
        print(f"\n[!] Gmail Fetch Error: {e}")
        return

    if not alerts:
        print("No new Google Alert emails found.")
        return

    alerts = remove_duplicate_links(alerts)

    for alert_idx, alert in enumerate(alerts, 1):
        print(f"\n[{alert_idx}] Alert Email: {alert['subject']} ({alert['date']})")
        links = alert["links"]

        if not links:
            print("  (No paper links found in this email)")
            continue

        print(f"  Found {len(links)} link(s):")
        for link_idx, link in enumerate(links, 1):
            print(f"    {link_idx}. {link['title']}")
            print(f"       URL: {link['url']}")

        for link in links:
            success = process_single_paper(link['title'], link['url'])
            if not success:
                failed_papers.append(link)
            # choice = input(f"\nAnalyze '{link['title']}'? [y/n/skip-email]: ").strip().lower()
            # if choice == 'y':
            #     success = process_single_paper(link['title'], link['url'])
            #     if not success:
            #         failed_papers.append(link)
            # elif choice == 'skip-email':
            #     print("Skipping remaining links in this email...")
            #     break
            # else:
            #     continue

def main():
    parser = argparse.ArgumentParser(description="Scholar Summary Agent")
    parser.add_argument("--url", help="Analyze a single paper URL directly, bypassing Gmail")
    parser.add_argument("--gmail", action="store_true", help="Run the Gmail alerts processing loop directly")
    args = parser.parse_args()

    # Ensure interests profile is set up
    ensure_interests_file()

    failed_papers = []

    if args.url:
        # User passed a direct URL
        title = input("Enter paper title (or press Enter to auto-generate): ").strip()
        if not title:
            title = "Manual Input Paper"
        success = process_single_paper(title, args.url)
        if not success:
            failed_papers.append({"title": title, "url": args.url})
    elif args.gmail:
        # User wants to run Gmail alerts directly
        run_gmail_flow(failed_papers)
    else:
        # Interactive mode
        print("=== Scholar Summary Prototype Agent ===")
        print("1. Search & Process Google Alert emails in Gmail")
        print("2. Retrieve & Analyze a paper from a direct URL")
        print("3. Provide feedback to update your Interest Profile")
        print("4. Exit")

        choice = input("\nSelect an option (1-3): ").strip()
        if choice == "1":
            run_gmail_flow(failed_papers)
        elif choice == "2":
            url = input("Enter paper URL: ").strip()
            if url:
                title = input("Enter paper title (or press Enter to auto-generate): ").strip()
                if not title:
                    title = "Manual Input Paper"
                success = process_single_paper(title, url)
                if not success:
                    failed_papers.append({"title": title, "url": url})
            else:
                print("Invalid URL.")
        elif choice == "3":
            feedback_process()
        elif choice == "4":
            print("Exiting. Goodbye!")
            return
        else:
            print("Invalid option.")
            return

    # Report of failed papers
    report_path = Path(config.REPORTS_DIR) / config.FAILED_PAPERS_FILE
    if failed_papers:
        print("\n" + "=" * 20 + " FAILED PAPERS REPORT " + "=" * 20)
        print("The following papers could not be retrieved and processed:")
        for idx, paper in enumerate(failed_papers, 1):
            print(f"{idx}. {paper['title']}")
            print(f"   URL: {paper['url']}")
        print("=" * 60)

        try:
            os.makedirs(config.REPORTS_DIR, exist_ok=True)
            content = "# Failed Papers Report\n\n"
            content += "The following papers could not be retrieved during the session. You may need to access them manually:\n\n"
            for idx, paper in enumerate(failed_papers, 1):
                content += f"{idx}. **{paper['title']}**\n"
                content += f"   - URL: {paper['url']}\n"
            report_path.write_text(content, encoding="utf-8")
            print(f"[+] Failed papers list saved to {report_path}")
        except Exception as e:
            print(f"[!] Error saving failed papers report to file: {e}")
    else:
        if report_path.exists():
            try:
                report_path.unlink()
                print(f"[+] Cleaned up previous failed papers report at {report_path}")
            except Exception as e:
                print(f"[!] Error deleting failed papers report: {e}")

if __name__ == "__main__":
    main()
