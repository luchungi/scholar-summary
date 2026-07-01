import aisuite as ai
import json
import re
import config

# Initialize the aisuite Client
# Configures the openai provider to hit Ollama's local OpenAI-compatible endpoint
client = ai.Client(
    provider_configs={
        "openai": {
            "base_url": config.OLLAMA_BASE_URL,
            "api_key": "ollama"  # Ollama does not require an API key
        }
    }
)

def get_effective_model():
    """
    Returns the configured Ollama model, or dynamically queries Ollama
    to fall back to the first available model if none is specified.
    """
    if config.OLLAMA_MODEL:
        if config.OLLAMA_MODEL.startswith("openai:"):
            return config.OLLAMA_MODEL
        return f"openai:{config.OLLAMA_MODEL}"
    
    # Dynamic fallback: query Ollama REST API tags
    try:
        import requests
        from urllib.parse import urlparse
        parsed = urlparse(config.OLLAMA_BASE_URL)
        host_url = f"{parsed.scheme}://{parsed.netloc}"
        res = requests.get(f"{host_url}/api/tags", timeout=2)
        if res.status_code == 200:
            data = res.json()
            models = data.get("models", [])
            if models:
                first_model = models[0]["name"]
                print(f"[!] No model configured in OLLAMA_MODEL. Dynamically falling back to: {first_model}")
                return f"openai:{first_model}"
    except Exception as e:
        print(f"[-] Error auto-detecting Ollama fallback model: {e}")
    
    return "openai:qwen3.6:27b-mlx"

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
    model_name = get_effective_model()
    print(f"Extracting paper title using model: {model_name}...")
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
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
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

def generate_paper_report(paper_title, paper_url, paper_text, user_interests):
    """
    Prompts the local LLM to analyze the paper and generate a report.
    """
    model_name = get_effective_model()
    print(f"Generating report using model: {model_name}...")

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

IMPORTANT: You MUST append the following ratings metadata block at the very end of your response. Ensure the scores are floats (e.g. 4.0, 3.5) and the justifications are short (1-2 sentences):
<ratings>
  <quality_rating>SCORE</quality_rating>
  <quality_justification>JUSTIFICATION</quality_justification>
  <relevance_rating>SCORE</relevance_rating>
  <relevance_justification>JUSTIFICATION</relevance_justification>
</ratings>
"""

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        raise ConnectionError(
            f"Failed to communicate with Ollama model '{model_name}' "
            f"at {config.OLLAMA_BASE_URL}.\nDetails: {e}\n"
            f"Please ensure Ollama is running and the local server is started."
        )

def update_user_interests(current_interests, user_feedback):
    """
    Prompts the local LLM to refine the user's interest profile based on their feedback.
    """
    model_name = get_effective_model()
    print(f"Updating interest profile using model: {model_name}...")

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
            model=model_name,
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
            f"Failed to communicate with Ollama to update interests.\nDetails: {e}"
        )

def propose_pdf_rule(url, html_links, error_context=None):
    """
    Prompts the local LLM to propose a PDF retrieval rule for a domain based on its HTML links.
    """
    model_name = get_effective_model()
    print(f"Proposing PDF retrieval rule using model: {model_name}...")

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
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"}
            )
        except Exception as json_err:
            print(f"[*] JSON Mode not supported or failed: {json_err}. Falling back to standard format.")
            response = client.chat.completions.create(
                model=model_name,
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

