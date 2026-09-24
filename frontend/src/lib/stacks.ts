// Keep in sync with backend (prompts/prompt_types.py).
// Order here determines order in dropdown
export enum Stack {
  HTML_TAILWIND = "html_tailwind",
  HTML_CSS = "html_css",
  REACT_TAILWIND = "react_tailwind",
  BOOTSTRAP = "bootstrap",
  VUE_TAILWIND = "vue_tailwind",
  IONIC_TAILWIND = "ionic_tailwind",
  REACT_NATIVE = "react_native",
}

export const STACK_DESCRIPTIONS: {
  [key in Stack]: { components: string[]; inBeta: boolean; label?: string };
} = {
  html_css: { components: ["HTML", "CSS"], inBeta: false },
  html_tailwind: { components: ["HTML", "Tailwind"], inBeta: false },
  react_tailwind: { components: ["React", "Tailwind"], inBeta: false },
  bootstrap: { components: ["Bootstrap"], inBeta: false },
  vue_tailwind: { components: ["Vue", "Tailwind"], inBeta: true },
  ionic_tailwind: { components: ["Ionic", "Tailwind"], inBeta: true },
  react_native: {
    components: ["React Native", "Expo"],
    inBeta: true,
    label: "React Native (Expo)",
  },
};

// A React Native project is one App.jsx previewed on a phone; every other
// stack is an index.html page.
export function isReactNativeStack(stack: Stack | undefined | null): boolean {
  return stack === Stack.REACT_NATIVE;
}

export function mainFilePath(stack: Stack | undefined | null): string {
  return isReactNativeStack(stack) ? "App.jsx" : "index.html";
}
