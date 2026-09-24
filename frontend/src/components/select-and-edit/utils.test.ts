import {
  buildReactNativeSelectedElementInstruction,
  buildSelectedElementInstruction,
  describeElementContext,
  describeReactNativeElement,
  nearestTestIdElement,
  reactNativeElementLabel,
} from "./utils";

// Minimal stand-in for a DOM element; jest runs in the node environment.
interface FakeElement {
  tagName: string;
  outerHTML: string;
  parentElement: FakeElement | null;
  ownerDocument: { getElementsByTagName: (tag: string) => FakeElement[] };
  getAttribute: (name: string) => string | null;
}

function fakeElement(tag: string, classAttr: string, outerHTML = ""): FakeElement {
  return {
    tagName: tag.toUpperCase(),
    outerHTML,
    parentElement: null,
    ownerDocument: { getElementsByTagName: () => [] },
    getAttribute: (name) => (name === "class" && classAttr ? classAttr : null),
  };
}

function asElement(el: FakeElement): Element {
  return el as unknown as Element;
}

describe("describeElementContext", () => {
  function buildPricingPage() {
    const body = fakeElement("body", "");
    const grid = fakeElement("div", "pricing-grid");
    const card = fakeElement("div", "pricing-card featured");
    const anchorHtml = '<a href="#" class="btn">Choose plan</a>';
    const basicBtn = fakeElement("a", "btn", anchorHtml);
    const proBtn = fakeElement("a", "btn", anchorHtml);
    const enterpriseBtn = fakeElement("a", "btn", anchorHtml);
    grid.parentElement = body;
    card.parentElement = grid;
    proBtn.parentElement = card;
    const doc = {
      getElementsByTagName: () => [basicBtn, proBtn, enterpriseBtn],
    };
    [basicBtn, proBtn, enterpriseBtn].forEach((el) => {
      el.ownerDocument = doc;
    });
    return { proBtn };
  }

  it("builds an ancestor path with classes", () => {
    const { proBtn } = buildPricingPage();
    const context = describeElementContext(asElement(proBtn));
    expect(context).toContain(
      "Element location: body > div.pricing-grid > div.pricing-card.featured > a.btn"
    );
  });

  it("notes the position among identical elements", () => {
    const { proBtn } = buildPricingPage();
    const context = describeElementContext(asElement(proBtn));
    expect(context).toContain("3 elements on the page share this exact markup");
    expect(context).toContain("number 2 of 3");
  });

  it("omits the duplicate note when the markup is unique", () => {
    const heading = fakeElement("h1", "title", "<h1 class=\"title\">Hi</h1>");
    heading.ownerDocument = { getElementsByTagName: () => [heading] };
    const context = describeElementContext(asElement(heading));
    expect(context).toContain("Element location: h1.title");
    expect(context).not.toContain("share this exact markup");
  });
});

describe("buildSelectedElementInstruction", () => {
  it("includes the instruction and the element html", () => {
    const result = buildSelectedElementInstruction(
      "Make the button red",
      '<button class="btn">Buy</button>'
    );
    expect(result).toContain("Make the button red");
    expect(result).toContain('<button class="btn">Buy</button>');
    expect(result).toContain("selected in the preview");
  });

  it("mentions that the snippet is rendered DOM, not source", () => {
    const result = buildSelectedElementInstruction(
      "Center it",
      "<div>x</div>"
    );
    expect(result).toContain("outerHTML captured from the rendered page");
  });

  it("truncates very large element html", () => {
    const hugeHtml = `<div>${"a".repeat(20000)}</div>`;
    const result = buildSelectedElementInstruction("Shrink it", hugeHtml);
    expect(result).toContain("truncated");
    expect(result.length).toBeLessThan(hugeHtml.length);
  });

  it("does not truncate small element html", () => {
    const result = buildSelectedElementInstruction(
      "Bold it",
      "<span>hello</span>"
    );
    expect(result).not.toContain("truncated");
  });

  it("includes the element context when provided", () => {
    const result = buildSelectedElementInstruction(
      "Make it red",
      '<a class="btn">Go</a>',
      "Element location: body > div.card > a.btn"
    );
    expect(result).toContain("Element location: body > div.card > a.btn");
  });

  it("omits the context block when not provided", () => {
    const result = buildSelectedElementInstruction(
      "Make it red",
      '<a class="btn">Go</a>'
    );
    expect(result).not.toContain("Element location:");
  });
});

// A React Native preview's DOM: react-native-web renders testID as data-testid.
interface FakeRnElement {
  testId: string | null;
  textContent: string;
  parentElement: FakeRnElement | null;
  getAttribute: (name: string) => string | null;
  closest: (selector: string) => FakeRnElement | null;
}

function rnElement(testId: string | null, textContent = "", parent: FakeRnElement | null = null): FakeRnElement {
  const el: FakeRnElement = {
    testId,
    textContent,
    parentElement: parent,
    getAttribute: (name) => (name === "data-testid" ? el.testId : null),
    closest: (selector) => {
      expect(selector).toBe("[data-testid]");
      let current: FakeRnElement | null = el;
      while (current && !current.testId) current = current.parentElement;
      return current;
    },
  };
  return el;
}

function buildSettingsScreen() {
  const screen = rnElement("screen");
  const list = rnElement("settings-list", "", screen);
  const row = rnElement("settings-row-about", "  About\n  Version 4.2.0 ", list);
  const title = rnElement(null, "About", row);
  return { screen, list, row, title };
}

describe("React Native selection", () => {
  it("selects the nearest element with a testID", () => {
    const { row, title } = buildSettingsScreen();
    expect(nearestTestIdElement(title as unknown as HTMLElement)).toBe(row);
    expect(nearestTestIdElement(row as unknown as HTMLElement)).toBe(row);
  });

  it("keeps the pointed element when nothing has a testID", () => {
    const orphan = rnElement(null, "Hi");
    expect(nearestTestIdElement(orphan as unknown as HTMLElement)).toBe(orphan);
  });

  it("describes the testID, the testIDs around it and its text", () => {
    const { row } = buildSettingsScreen();
    const description = describeReactNativeElement(row as unknown as Element);
    expect(description).toEqual({
      testId: "settings-row-about",
      testIdPath: ["screen", "settings-list", "settings-row-about"],
      text: "About Version 4.2.0",
    });
    expect(reactNativeElementLabel(description)).toBe('testID="settings-row-about"');
  });

  it("reads rendered text when there is some, so sibling blocks stay apart", () => {
    const row = Object.assign(rnElement("row", "TitleSubtitle"), { innerText: "Title\nSubtitle" });
    expect(describeReactNativeElement(row as unknown as Element).text).toBe("Title Subtitle");
  });

  it("caps long text", () => {
    const long = rnElement("body-copy", "word ".repeat(100));
    const { text } = describeReactNativeElement(long as unknown as Element);
    expect(text.length).toBeLessThanOrEqual(121);
    expect(text.endsWith("…")).toBe(true);
  });

  it("builds an instruction that locates the element by testID", () => {
    const { row } = buildSettingsScreen();
    const result = buildReactNativeSelectedElementInstruction(
      "Make it red",
      describeReactNativeElement(row as unknown as Element)
    );
    expect(result.startsWith("Make it red\n\n")).toBe(true);
    expect(result).toContain('the one with testID="settings-row-about"');
    expect(result).toContain("testIDs from the screen down to it: screen > settings-list > settings-row-about");
    expect(result).toContain('Its text: "About Version 4.2.0"');
    expect(result).toContain("by its testID");
    expect(result).not.toContain("outerHTML");
  });

  it("says so when the element has no testID", () => {
    const result = buildReactNativeSelectedElementInstruction("Bold it", {
      testId: null,
      testIdPath: [],
      text: "Hi",
    });
    expect(result).toContain("It has no testID.");
    expect(result).not.toContain("testIDs from the screen");
  });
});
