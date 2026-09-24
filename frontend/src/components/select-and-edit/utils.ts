// Cap the element HTML included in the prompt. The model already receives the
// full current code, so the snippet only needs to identify the element.
const MAX_ELEMENT_HTML_LENGTH = 12000;

const MAX_PATH_DEPTH = 6;

function describeNode(el: Element): string {
  const tag = el.tagName.toLowerCase();
  const classAttr = el.getAttribute("class") || "";
  const classes = classAttr.split(/\s+/).filter(Boolean).slice(0, 3);
  return tag + classes.map((c) => `.${c}`).join("");
}

// The outerHTML alone can't identify the element when siblings share identical
// markup (e.g. three "Choose plan" buttons styled by a parent class), so also
// describe where it sits in the DOM.
export function describeElementContext(el: Element): string {
  const parts: string[] = [];
  let current: Element | null = el;
  while (current && parts.length < MAX_PATH_DEPTH) {
    if (current.tagName.toLowerCase() === "html") break;
    parts.unshift(describeNode(current));
    current = current.parentElement;
  }
  const lines = [`Element location: ${parts.join(" > ")}`];

  const identical = Array.from(
    el.ownerDocument.getElementsByTagName(el.tagName)
  ).filter((other) => other.outerHTML === el.outerHTML);
  if (identical.length > 1) {
    const position = identical.indexOf(el) + 1;
    lines.push(
      `${identical.length} elements on the page share this exact markup; the user selected number ${position} of ${identical.length} in document order. Edit only that one and leave the other copies exactly as they are. Because the markup repeats, do not locate the element by its own markup alone — anchor the edit with unique surrounding context (its parent element or a distinguishing ancestor class from the location path above), or scope a style change through that ancestor. Any search/replace whose search text matches more than one place will hit the wrong copy.`
    );
  }
  return lines.join("\n");
}

// React Native: App.jsx's testID props become data-testid in the preview.
const TEST_ID_ATTRIBUTE = "data-testid";
const MAX_TEST_ID_DEPTH = 8;
const MAX_TEXT_SNIPPET = 120;

export interface ReactNativeElementDescription {
  testId: string | null;
  // testIDs of the elements it sits in, outermost first, ending with its own.
  testIdPath: string[];
  text: string;
}

// The element to select for a pointer target in a React Native preview:
// the nearest element with a testID.
export function nearestTestIdElement(element: HTMLElement): HTMLElement {
  return (element.closest?.(`[${TEST_ID_ATTRIBUTE}]`) as HTMLElement | null) ?? element;
}

export function describeReactNativeElement(el: Element): ReactNativeElementDescription {
  const testIdPath: string[] = [];
  let current: Element | null = el;
  while (current && testIdPath.length < MAX_TEST_ID_DEPTH) {
    const testId = current.getAttribute(TEST_ID_ATTRIBUTE);
    if (testId) testIdPath.unshift(testId);
    current = current.parentElement;
  }
  // innerText separates react-native-web's sibling Text blocks; textContent
  // would run "Notifications" into "Push, email, SMS".
  const rendered = (el as Partial<HTMLElement>).innerText;
  const text = (typeof rendered === "string" ? rendered : el.textContent ?? "")
    .replace(/\s+/g, " ")
    .trim();
  return {
    testId: el.getAttribute(TEST_ID_ATTRIBUTE),
    testIdPath,
    text: text.length > MAX_TEXT_SNIPPET ? `${text.slice(0, MAX_TEXT_SNIPPET)}…` : text,
  };
}

// How the selection is labelled in the sidebar, history and overlays.
export function reactNativeElementLabel(description: ReactNativeElementDescription): string {
  return description.testId ? `testID="${description.testId}"` : "element";
}

export function buildReactNativeSelectedElementInstruction(
  instruction: string,
  description: ReactNativeElementDescription
): string {
  const lines = [
    instruction,
    "",
    description.testId
      ? `Apply the change to the element the user selected in the preview: the one with testID="${description.testId}".`
      : "Apply the change to the element the user selected in the preview. It has no testID.",
  ];
  if (description.testIdPath.length > (description.testId ? 1 : 0)) {
    lines.push(`testIDs from the screen down to it: ${description.testIdPath.join(" > ")}`);
  }
  if (description.text) {
    lines.push(`Its text: "${description.text}"`);
  }
  lines.push(
    "",
    "Find that element in App.jsx by its testID (rows of a list build theirs from the item, such as `row-${item.id}`) and change only it and its rendering logic, leaving the rest of App.jsx unchanged."
  );
  return lines.join("\n");
}

export function buildSelectedElementInstruction(
  instruction: string,
  elementHtml: string,
  elementContext?: string
): string {
  const truncated =
    elementHtml.length > MAX_ELEMENT_HTML_LENGTH
      ? elementHtml.slice(0, MAX_ELEMENT_HTML_LENGTH) +
        "\n<!-- truncated; locate the element in the current code -->"
      : elementHtml;

  return `${instruction}

Apply the change to this specific element that the user selected in the preview:

\`\`\`html
${truncated}
\`\`\`
${elementContext ? `\n${elementContext}\n` : ""}
This snippet is the element's outerHTML captured from the rendered page, so it can differ from the source code (for example JSX uses className, Vue templates use directives and interpolations, and frameworks like Ionic or Bootstrap may inject classes or attributes at runtime). Find the code that produces this element and apply the change there, leaving unrelated code untouched.`;
}
