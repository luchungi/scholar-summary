import aisuite as ai
import json
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
        "You are a helpful assistant. Your task is to identify and extract the title of the academic paper "
        "from the provided text snippet. Respond with ONLY the exact title. Do not include any introductory text, "
        "quotes, markdown bold, or other formatting. The output should be clean text."
    )
    user_prompt = f"""Identify the title of the academic paper from the following text snippet:
---
{snippet}
---

Title:"""
    try:
        response = client.chat.completions.create(
            model=config.LM_STUDIO_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        title = response.choices[0].message.content.strip()
        if title.startswith('"') and title.endswith('"'):
            title = title[1:-1].strip()
        elif title.startswith("'") and title.endswith("'"):
            title = title[1:-1].strip()
        title = title.replace("**", "").replace("*", "").strip()
        return title
    except Exception as e:
        print(f"[-] Error extracting paper title: {e}")
        return None

def generate_paper_report(paper_title, paper_url, paper_text, user_interests):
    """
    Prompts the local LLM to analyze the paper and generate a report.
    """
    print(f"Generating report using model: {config.LM_STUDIO_MODEL}...")

    system_prompt = (
        "You are an expert Research Assistant Agent. Your role is to read academic papers, "
        "summarize them, analyze their contributions to the literature, and evaluate their "
        "relevance to a researcher's interests."
    )

    user_prompt = f"""Here is the researcher's interest profile:
---
{user_interests}
---

Please analyze the following paper:
Title: {paper_title}
URL: {paper_url}

Paper Text:
---
{paper_text}
---

Generate a comprehensive, structured report in markdown and using LaTeX for equations that addresses the following points:

### 1. Access to full text
If the paper is behind a paywall or not fully accessible, highlight this to the user

### 2. Rate the quality of the paper on a scale of 1 to 5, with 5 being the highest quality. Provide a brief justification for your rating.

### 3. Relevance to User Interests
Analyze how this paper connects with the user's interests listed in their profile and give a rating on a scale of 1 to 5 for relevance. Point out specific projects, keywords, or topics that are relevant, and explain why this paper is worth their attention (or why it may not be).

### 4. Key High-Level Ideas
Provide a clear, high-level summary of the paper. Explain what problem it solves, the proposed method/architecture, and the key findings or results. Keep it accessible yet detailed enough to capture the technical essence.

### 5. Fit in the Literature & Contributions
Explain how the paper fits into the wider academic literature. Identify its core contributions (e.g., novel architecture, improved efficiency, new datasets, or benchmarks) and how it compares to existing approaches.

"""

    try:
        response = client.chat.completions.create(
            model=config.LM_STUDIO_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
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
        "interest profile in Markdown format based on their feedback."
    )

    user_prompt = f"""Here is the researcher's current Interest Profile:
---
{current_interests}
---

Here is the feedback provided by the researcher:
---
{user_feedback}
---

Please update the interest profile based on this feedback. You can add new research interests, modify existing ones, remove topics that are no longer relevant, or add/edit keywords.
Maintain the exact structure and formatting (Markdown headers, bullet points, inline code) of the profile.

Return ONLY the updated Markdown profile. Do not include any preambles, explanations, code blocks, or markdown code fences (like ```markdown ... ```).
"""

    try:
        response = client.chat.completions.create(
            model=config.LM_STUDIO_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        raw_output = response.choices[0].message.content
        return clean_llm_markdown(raw_output)
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

