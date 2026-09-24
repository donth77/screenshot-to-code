from codegen.utils import extract_file_content, extract_html_content, extract_jsx_content, main_file_path


def test_extract_html_content_from_wrapped_file_tag() -> None:
    text = '<file path="index.html">\n<html><body><p>Hello</p></body></html>\n</file>'

    result = extract_html_content(text)

    assert result == "<html><body><p>Hello</p></body></html>"


# React Native: App.jsx extraction never runs HTML extraction.

JSX_APP = """import React from 'react';
import { Text } from 'react-native';

export default function App() {
  return <Text>{'<html><body>not a web page</body></html>'}</Text>;
}"""


def test_main_file_path_per_stack() -> None:
    assert main_file_path("react_native") == "App.jsx"
    assert main_file_path("html_tailwind") == "index.html"
    assert main_file_path(None) == "index.html"


def test_extract_jsx_keeps_code_that_mentions_html() -> None:
    assert extract_jsx_content(JSX_APP) == JSX_APP
    assert extract_file_content(JSX_APP, "App.jsx") == JSX_APP
    # HTML extraction would have cut the file down to the string literal.
    assert extract_file_content(JSX_APP, "index.html") != JSX_APP


def test_extract_jsx_unwraps_file_tags_and_fences() -> None:
    assert extract_jsx_content(f'<file path="App.jsx">\n{JSX_APP}\n</file>') == JSX_APP
    assert extract_jsx_content(f"Here it is:\n```jsx\n{JSX_APP}\n```\nDone.") == JSX_APP
    assert extract_jsx_content(f'<file path="App.jsx">\n```javascript\n{JSX_APP}\n```\n</file>') == JSX_APP


def test_extract_jsx_rejects_prose() -> None:
    assert extract_jsx_content("I built the settings screen with a list of rows.") == ""
