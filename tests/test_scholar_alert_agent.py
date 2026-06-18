import unittest

from scholar_alert_agent import (
    PaperAnalysis,
    PaperCandidate,
    ScholarAlertEmail,
    ScholarSummaryAgent,
    extract_paper_candidates,
    format_report,
    is_google_scholar_alert,
)


class FakeSource:
    def fetch_google_scholar_alerts(self, limit: int = 20):
        return [
            ScholarAlertEmail(
                subject="Google Scholar - new articles",
                sender="scholaralerts-noreply@google.com",
                body=(
                    "A Great Paper on Agents\n"
                    "https://example.org/papers/agent-paper\n\n"
                    "Another Paper\n"
                    "https://example.org/papers/another-paper\n"
                ),
            )
        ]


class FakeAnalyzer:
    def analyze_paper(self, paper: PaperCandidate, user_interest_prompts):
        return PaperAnalysis(
            title=paper.title,
            url=paper.url,
            key_ideas=f"Key ideas for {paper.title}",
            literature_context="Related to prior work in autonomous agents",
            contribution="Provides a practical workflow",
            interest_fit=f"Matches interests: {', '.join(user_interest_prompts)}",
        )


class ScholarAlertAgentTests(unittest.TestCase):
    def test_google_scholar_alert_detection(self):
        self.assertTrue(
            is_google_scholar_alert(
                ScholarAlertEmail(
                    subject="Google Scholar Alerts",
                    sender="scholaralerts-noreply@google.com",
                    body="",
                )
            )
        )
        self.assertFalse(
            is_google_scholar_alert(
                ScholarAlertEmail(
                    subject="Weekly newsletter",
                    sender="updates@example.com",
                    body="",
                )
            )
        )

    def test_extract_paper_candidates(self):
        email_item = ScholarAlertEmail(
            subject="Google Scholar",
            sender="scholaralerts-noreply@google.com",
            body=(
                "Paper One\n"
                "https://example.org/one\n"
                "[Paper Two](https://example.org/two)\n"
                "Paper One\n"
                "https://example.org/one\n"
            ),
        )

        papers = extract_paper_candidates(email_item)
        self.assertEqual(len(papers), 2)
        self.assertEqual(papers[0].title, "Paper One")
        self.assertEqual(papers[0].url, "https://example.org/one")

    def test_agent_run_builds_required_report_sections(self):
        agent = ScholarSummaryAgent(source=FakeSource(), analyzer=FakeAnalyzer())
        report = agent.run(["multi-agent systems", "paper summarization"])

        self.assertIn("# Scholar Alert Report", report)
        self.assertIn("### 1) High-level key ideas", report)
        self.assertIn("### 2) Link to literature and contribution", report)
        self.assertIn("### 3) Fit with user interests", report)
        self.assertIn("multi-agent systems", report)

    def test_format_report_no_analyses(self):
        report = format_report([], ["ai"])
        self.assertIn("No Google Scholar alert papers were found", report)


if __name__ == "__main__":
    unittest.main()
