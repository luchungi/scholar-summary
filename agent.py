import aisuite as ai
import json
import re
import config

# Initialize the aisuite Client
# Configures the openai provider to hit LM Studio's local endpoint
client = ai.Client(
    provider_configs={
        "openai": {
            "base_url": config.LM_STUDIO_BASE_URL,
            "api_key": config.LM_STUDIO_API_KEY
        }
    }
)

def clean_llm_markdown(text):
    """
    Cleans up any wrapping code fences (e.g., ```markdown ... ```)
    that the LLM might have returned.
    """
    text = text.strip()
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()

def extract_paper_title(paper_text):
    """
    Prompts the local LLM to extract the paper title from the paper text.
    """
    print(f"Extracting paper title using model: {config.LM_STUDIO_MODEL}...")
    snippet = paper_text[:3000]
    system_prompt = (
        "You are a helpful assistant. Your task is to extract the exact title of the academic paper "
        "from the provided text snippet. Return the title wrapped in `<title>` and `</title>` tags. "
        "Do not include any introductory text, author list, publisher information, page numbers, or general comments. "
        "Always ignore metadata like journal titles, copyright headers, and 'arXiv:xxxx.xxxxx'."
    )
    user_prompt = f"""Here are examples of title extraction:

Example 1 Snippet:
---
arXiv:1512.03385v1 [cs.CV] 10 Dec 2015
Deep Residual Learning for Image Recognition
Kaiming He Xiangyu Zhang Shaoqing Ren Jian Sun
Microsoft Research
Abstract
Deeper neural networks are more difficult to train. We
present a residual learning framework to ease the training...
---
Output:
<title>Deep Residual Learning for Image Recognition</title>

Example 2 Snippet:
---
JOURNAL OF NEUROSCIENCE, VOL 42, NO 3
The Role of Dopamine in Decision Making
Jane Doe, John Smith
University of Science
Abstract: Dopamine is known to play a key role...
---
Output:
<title>The Role of Dopamine in Decision Making</title>

Now, extract the title from the following snippet:
---
{snippet}
---
Output:"""
    try:
        response = client.chat.completions.create(
            model=config.LM_STUDIO_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1
        )
        raw_output = response.choices[0].message.content.strip()
        match = re.search(r'<title>(.*?)</title>', raw_output, re.DOTALL | re.IGNORECASE)
        if match:
            title = match.group(1).strip()
        else:
            title = raw_output
            if title.startswith('"') and title.endswith('"'):
                title = title[1:-1].strip()
            elif title.startswith("'") and title.endswith("'"):
                title = title[1:-1].strip()
            title = title.replace("**", "").replace("*", "").strip()
        return title
    except Exception as e:
        print(f"[-] Error extracting paper title: {e}")
        return None

def assess_relevance(paper_title, paper_snippet, user_interests):
    """
    Quick relevance pre-check from title + abstract snippet.
    Returns (score: float | None, reason: str).
    """
    print(f"Pre-checking relevance using model: {config.LM_STUDIO_MODEL}...")
    system_prompt = (
        "You are a strict research-triage assistant. Given a researcher's interest profile and the "
        "title plus opening text of a paper, rate how relevant the paper is to the profile on a 1-5 scale:\n"
        "5 = direct hit on a Primary Area of Interest.\n"
        "4 = strong overlap with a Primary Area from a different angle.\n"
        "3 = fits a Secondary Area of Interest.\n"
        "2 = only tangential or purely methodological overlap.\n"
        "1 = keyword-only overlap; the actual topic is outside the profile.\n"
        "Respond with EXACTLY this format and nothing else:\n"
        "<relevance_score>SCORE</relevance_score>\n"
        "<reason>ONE short sentence</reason>"
    )
    user_prompt = f"""Researcher's interest profile:
---
{user_interests}
---

Paper title: {paper_title}

Opening text of the paper:
---
{paper_snippet}
---
"""
    try:
        response = client.chat.completions.create(
            model=config.LM_STUDIO_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1
        )
        raw = response.choices[0].message.content
        score_match = re.search(r'<relevance_score>\s*([0-9.]+)\s*</relevance_score>', raw, re.DOTALL | re.IGNORECASE)
        reason_match = re.search(r'<reason>(.*?)</reason>', raw, re.DOTALL | re.IGNORECASE)
        score = float(score_match.group(1)) if score_match else None
        reason = reason_match.group(1).strip() if reason_match else ""
        return score, reason
    except Exception as e:
        print(f"[-] Error during relevance pre-check (paper will be analyzed anyway): {e}")
        return None, ""

def generate_paper_report(paper_title, paper_url, paper_text, user_interests, access_info=None):
    """
    Prompts the local LLM to analyze the paper and generate a report.
    access_info: optional factual note (computed by the retriever) about how the text
    was obtained (PDF vs HTML scrape, char count, truncation), passed as fact to the model.
    """
    print(f"Generating report using model: {config.LM_STUDIO_MODEL}...")

    system_prompt = (
        "You are a skeptical peer reviewer with expertise in quantitative finance, stochastic analysis, "
        "machine learning, and reinforcement learning. You read academic papers critically: you do not "
        "take the authors' claims at face value, you flag unsupported claims, unrealistic experiments "
        "(e.g. backtests without transaction costs, in-sample-only results, look-ahead/data-snooping bias), "
        "missing baselines or ablations, and gaps in mathematical rigor. You summarize papers accurately "
        "and evaluate their relevance to a researcher's interest profile."
    )

    access_section = ""
    if access_info:
        access_section = f"""
Factual note on how the text was obtained (do NOT speculate about access beyond this):
{access_info}
"""

    user_prompt = f"""Here is the researcher's interest profile:
---
{user_interests}
---

Please analyze the following paper:
Title: {paper_title}
URL: {paper_url}
{access_section}
Paper Text:
---
{paper_text}
---

Generate a comprehensive, structured report in markdown and using LaTeX for equations with the following sections:

### 1. Paper Metadata
Extract from the text if available: authors, affiliation(s), venue/journal, and year. Write "Unknown" for anything not stated in the text. Do not guess.

### 2. Quality Rating
Rate the quality of the paper on a scale of 1 to 5 using this rubric, and justify the score against the rubric:
- 5: Meets the bar of a top venue/journal (e.g. NeurIPS/ICML, Mathematical Finance, Annals of Applied Probability, JF/JFE): rigorous and correct proofs or well-founded stochastic modeling; strong empirical methodology (realistic backtests with transaction costs, out-of-sample evaluation, strong baselines, ablations); clearly novel contribution.
- 4: Solid, credible work with minor gaps (e.g. limited baselines, restrictive assumptions that are honestly stated).
- 3: Competent but limited: incremental novelty, weak evaluation (in-sample only, few assets/short periods, no ablations), or proofs/derivations with gaps.
- 2: Significant flaws: unrealistic experiments (no transaction costs, look-ahead bias, data snooping), unsupported claims, or imprecise/hand-wavy mathematics.
- 1: Serious errors, pseudo-rigor, or predatory-journal characteristics.
Calibration: most papers from alert feeds (preprints, theses, minor journals) should land at 2-3. Reserve 4+ for work that genuinely meets top-venue standards. Judge what is demonstrated in the text, not what the authors claim.

### 3. Relevance to User Interests
Rate relevance to the profile on a scale of 1 to 5 using this rubric:
- 5: Direct hit on a Primary Area of Interest.
- 4: Strong overlap with a Primary Area from a different angle.
- 3: Fits a Secondary Area of Interest.
- 2: Only tangential or purely methodological overlap.
- 1: Keyword-only overlap; the topic is outside the profile.
Name the specific interest areas or keywords that match, and explain why the paper is or is not worth the researcher's attention.

### 4. Key High-Level Ideas
Provide a clear, high-level summary: the problem it solves, the proposed method/model/architecture, and the key findings or results. Accessible yet detailed enough to capture the technical essence.

### 5. Fit in the Literature & Contributions
Explain how the paper fits into the wider academic literature, its core contributions (e.g. novel theory, architecture, improved efficiency, new datasets or benchmarks), and how it compares to existing approaches.

IMPORTANT: You MUST append the following ratings metadata block at the very end of your response. Ensure the scores are floats (e.g. 4.0, 3.5) consistent with the rubrics above and the justifications are short (1-2 sentences):
<ratings>
  <quality_rating>SCORE</quality_rating>
  <quality_justification>JUSTIFICATION</quality_justification>
  <relevance_rating>SCORE</relevance_rating>
  <relevance_justification>JUSTIFICATION</relevance_justification>
</ratings>
"""

    try:
        response = client.chat.completions.create(
            model=config.LM_STUDIO_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=config.LLM_TEMPERATURE
        )
        return response.choices[0].message.content
    except Exception as e:
        raise ConnectionError(
            f"Failed to communicate with LM Studio model '{config.LM_STUDIO_MODEL}' "
            f"at {config.LM_STUDIO_BASE_URL}.\nDetails: {e}\n"
            f"Please ensure LM Studio is running and the local server is started."
        )

def update_user_interests(current_interests, user_feedback):
    """
    Prompts the local LLM to refine the user's interest profile based on their feedback.
    """
    print(f"Updating interest profile using model: {config.LM_STUDIO_MODEL}...")

    system_prompt = (
        "You are an expert Profile Manager Agent. Your role is to update a researcher's "
        "interest profile in Markdown format based on their feedback. "
        "Wrap the updated Markdown profile inside `<profile>` and `</profile>` tags. "
        "Do not include any preambles, explanations, or general conversational text outside the tags."
    )

    user_prompt = f"""Here is an example of a profile update:

Example Current Profile:
# User Research Interests
## Primary Areas
* **Machine Learning**: Deep learning models.
## Keywords
`transformer`.

Example Feedback:
"I want to focus less on general machine learning and more on LLMs, especially agentic workflows. Let's add the keyword 'langgraph'."

Example Output:
<profile>
# User Research Interests
## Primary Areas
* **Large Language Models**: Focus on LLMs, agentic workflows, and tool use.
## Keywords
`transformer`, `langgraph`.
</profile>

Now, update the current profile based on the feedback below:

Current Profile:
---
{current_interests}
---

Feedback:
---
{user_feedback}
---

Output:"""

    try:
        response = client.chat.completions.create(
            model=config.LM_STUDIO_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        raw_output = response.choices[0].message.content.strip()
        match = re.search(r'<profile>(.*?)</profile>', raw_output, re.DOTALL | re.IGNORECASE)
        if match:
            cleaned = match.group(1).strip()
        else:
            cleaned = clean_llm_markdown(raw_output)
        return cleaned
    except Exception as e:
        raise ConnectionError(
            f"Failed to communicate with LM Studio to update interests.\nDetails: {e}"
        )

def propose_pdf_rule(url, html_links, error_context=None):
    """
    Prompts the local LLM to propose a PDF retrieval rule for a domain based on its HTML links.
    """
    print(f"Proposing PDF retrieval rule using model: {config.LM_STUDIO_MODEL}...")

    system_prompt = (
        "You are an expert Web Scraping and Automation Agent. Your task is to analyze the URL and the list of hyperlinks "
        "on a web page to propose a rule that extracts the direct PDF download URL.\n"
        "You must respond with ONLY a valid JSON object matching the rule schema, containing no other explanation or code fences."
    )

    schema_desc = """
The rule JSON object must have one of these formats:
1. Regex replacement rule (if the PDF URL can be derived from the current URL):
{
  "type": "regex_replace",
  "pattern": "^https?://domain\\\\.org/some-path/(?P<id>\\\\d+)",
  "replacement": "https://domain.org/pdf/{id}"
}

2. CSS Selector rule (if the PDF URL is present on the page as a link):
{
  "type": "css_selector",
  "selector": "a.download-pdf",
  "attribute": "href" // optional, defaults to "href"
}

3. No PDF rule (if the page is paywalled or has no PDF link):
{
  "type": "none"
}
"""

    user_prompt = f"""Landing Page URL: {url}

Here is a list of links (anchor tags text and hrefs) found on the page:
---
{html_links}
---

{schema_desc}
"""

    if error_context:
        user_prompt += f"""
IMPORTANT: A previous rule attempt failed with the following error/context:
{error_context}
Please analyze this error, inspect the link structure again, and propose a DIFFERENT, corrected rule.
"""

    user_prompt += "\nReturn ONLY the JSON object. Do not wrap it in markdown code block ticks."

    try:
        try:
            response = client.chat.completions.create(
                model=config.LM_STUDIO_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"}
            )
        except Exception as json_err:
            print(f"[*] JSON Mode not supported or failed: {json_err}. Falling back to standard format.")
            response = client.chat.completions.create(
                model=config.LM_STUDIO_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ]
            )
        raw_output = response.choices[0].message.content.strip()
        cleaned = clean_llm_markdown(raw_output)
        rule = json.loads(cleaned)
        return rule
    except Exception as e:
        print(f"[-] Error proposing PDF rule: {e}")
        raise ValueError(f"Failed to generate valid PDF rule: {e}")

