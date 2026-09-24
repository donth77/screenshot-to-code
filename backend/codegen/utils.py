import re


def extract_html_content(text: str) -> str:
    file_match = re.search(
        r"<file\s+path=\"[^\"]+\">\s*(.*?)\s*</file>",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if file_match:
        return extract_html_content(file_match.group(1).strip())

    # First, strip markdown code fences if present
    text = re.sub(r'^```html?\s*\n?', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n?```\s*$', '', text, flags=re.MULTILINE)

    # Try to find DOCTYPE + html tags together
    match_with_doctype = re.search(
        r"(<!DOCTYPE\s+html[^>]*>.*?<html.*?>.*?</html>)", text, re.DOTALL | re.IGNORECASE
    )
    if match_with_doctype:
        return match_with_doctype.group(1)

    # Fall back to just <html> tags
    match = re.search(r"(<html.*?>.*?</html>)", text, re.DOTALL)
    if match:
        return match.group(1)
    else:
        # Otherwise, we just send the previous HTML over
        print(
            "[HTML Extraction] No <html> tags found in the generated content"
        )
        return text


HTML_MAIN_PATH = "index.html"
REACT_NATIVE_MAIN_PATH = "App.jsx"


def main_file_path(stack: str | None) -> str:
    """The single file the agent writes for a stack."""
    return REACT_NATIVE_MAIN_PATH if stack == "react_native" else HTML_MAIN_PATH


def extract_jsx_content(text: str) -> str:
    """The code of an App.jsx from a model reply or tool argument.

    Unwraps a <file> element or a code fence. Never looks for <html>: a JSX
    string can contain one, and HTML extraction would cut the file there.
    Prose with no code (no wrapper, fence, import or export) gives "", so a
    run that ends without writing the file fails instead of saving the prose.
    """
    file_match = re.search(
        r"<file\s+path=\"[^\"]+\">\s*(.*?)\s*</file>",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if file_match:
        text = file_match.group(1)
    fence_match = re.search(
        r"```(?:jsx|javascript|js|tsx|typescript)?[ \t]*\n(.*?)\n?```",
        text,
        re.DOTALL,
    )
    if fence_match:
        return fence_match.group(1).strip()
    if file_match:
        return text.strip()
    if re.search(r"^\s*(import|export)\b", text, re.MULTILINE):
        return text  # plain code, exactly as written
    return ""


def extract_file_content(text: str, path: str) -> str:
    """The code for the file at ``path`` from a model reply or tool argument."""
    if path.endswith(".jsx"):
        return extract_jsx_content(text)
    return extract_html_content(text)
