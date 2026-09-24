import { RefObject, useCallback, useEffect, useRef, useState } from "react";
import { useAppStore } from "../../store/app-store";
import {
  applySelectModeCursor,
  hideHoverOverlay,
  hideSelectionOverlay,
  removeHoverOverlay,
  removeSelectModeCursor,
  removeSelectionOverlay,
  showHoverOverlay,
  showSelectionOverlay,
} from "./overlays";

// Maps the element under the pointer to the element to select. React Native
// previews select the nearest element with a testID.
export type SelectTargetResolver = (element: HTMLElement) => HTMLElement;

const selectElementItself: SelectTargetResolver = (element) => element;

// Select-and-edit inside a same-origin preview iframe: capture-phase
// listeners on the frame's window, hover and selection rings, the crosshair
// cursor, and the selection in the app store.
export function useSelectAndEditFrame(
  iframeRef: RefObject<HTMLIFrameElement>,
  resolveTarget: SelectTargetResolver = selectElementItself
) {
  // Select and edit functionality
  const [clickEvent, setClickEvent] = useState<MouseEvent | null>(null);
  const resolveTargetRef = useRef(resolveTarget);
  useEffect(() => {
    resolveTargetRef.current = resolveTarget;
  }, [resolveTarget]);

  // In select-and-edit mode, intercept clicks in the capture phase so the
  // generated app's own handlers (React/Vue listeners, Bootstrap/Ionic
  // behaviors, link navigation, form submits) never fire while selecting.
  const handleIframeClick = useCallback((event: MouseEvent) => {
    if (!inSelectAndEditModeRef.current) return;
    event.preventDefault();
    event.stopPropagation();
    setClickEvent(event);
  }, []);

  // Suppress the rest of the pointer sequence (and form submits) while
  // selecting, since app handlers can be bound to those events too.
  const handleIframeInteraction = useCallback((event: Event) => {
    if (!inSelectAndEditModeRef.current) return;
    event.preventDefault();
    event.stopPropagation();
  }, []);

  const handleIframeLinkClick = useCallback((event: MouseEvent) => {
    const target = (event.target as HTMLElement).closest?.("a");
    if (!target) return;
    const href = target.getAttribute("href");
    if (href && href.startsWith("#")) {
      event.preventDefault();
    }
  }, []);

  // Devtools-style hover ring while selecting
  const hoveredElementRef = useRef<HTMLElement | null>(null);

  const handleIframeMouseOver = useCallback((event: MouseEvent) => {
    if (!inSelectAndEditModeRef.current) return;
    const pointed = event.target as HTMLElement;
    if (!pointed || !pointed.getBoundingClientRect) return;
    const target = resolveTargetRef.current(pointed);

    // The locked target owns this space. Avoid stacking the lighter hover
    // treatment over it, which can obscure the stronger selection ring/label.
    const selected = useAppStore.getState().selectedElement;
    if (selected && (target === selected || selected.contains(target))) {
      hoveredElementRef.current = null;
      hideHoverOverlay(target.ownerDocument);
      return;
    }

    hoveredElementRef.current = target;
    showHoverOverlay(target);
  }, []);

  const handleIframeMouseOut = useCallback((event: MouseEvent) => {
    if (!inSelectAndEditModeRef.current) return;
    // Only when the pointer leaves the iframe viewport entirely
    if (event.relatedTarget) return;
    hoveredElementRef.current = null;
    hideHoverOverlay((event.target as HTMLElement)?.ownerDocument);
  }, []);

  // Keep the rings glued to their elements while the page scrolls or
  // resizes under a stationary cursor.
  const handleIframeReposition = useCallback(() => {
    if (!inSelectAndEditModeRef.current) return;
    const hovered = hoveredElementRef.current;
    if (hovered && hovered.isConnected) {
      showHoverOverlay(hovered);
    }
    const selected = useAppStore.getState().selectedElement;
    if (selected && selected.isConnected) {
      showSelectionOverlay(selected);
    }
  }, []);

  // Escape exits select mode even when focus is inside the iframe.
  const handleIframeKeyDown = useCallback((event: KeyboardEvent) => {
    if (!inSelectAndEditModeRef.current) return;
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    useAppStore.getState().disableInSelectAndEditMode();
  }, []);

  const {
    inSelectAndEditMode,
    selectedElement,
    setSelectedElement,
  } = useAppStore();

  const inSelectAndEditModeRef = useRef(inSelectAndEditMode);
  useEffect(() => {
    inSelectAndEditModeRef.current = inSelectAndEditMode;
  }, [inSelectAndEditMode]);

  // Handle click events to select elements
  useEffect(() => {
    if (!inSelectAndEditModeRef.current || !clickEvent) {
      return;
    }

    const clicked = clickEvent.target as HTMLElement;
    if (!clicked) return;
    const targetElement = resolveTargetRef.current(clicked);

    // Replace the transient hover treatment with the visually stronger locked
    // target immediately; hovering other elements remains available afterward.
    hoveredElementRef.current = null;
    hideHoverOverlay(targetElement.ownerDocument);
    setSelectedElement(targetElement);
  }, [clickEvent, setSelectedElement]);

  // Render the selection ring for whatever element is currently selected
  // (clearing it when the selection is cleared from anywhere, e.g. the
  // sidebar's X button or after submitting an edit).
  useEffect(() => {
    if (selectedElement && selectedElement.isConnected) {
      showSelectionOverlay(selectedElement);
      return;
    }
    hideSelectionOverlay(iframeRef.current?.contentWindow?.document);
  }, [selectedElement, iframeRef]);

  // Apply/remove select-mode side effects (cursor, hover and selection
  // rings) when the mode toggles.
  useEffect(() => {
    const doc = iframeRef.current?.contentWindow?.document;
    if (inSelectAndEditMode) {
      applySelectModeCursor(doc);
      return;
    }
    if (selectedElement) {
      setSelectedElement(null);
    }
    hoveredElementRef.current = null;
    removeHoverOverlay(doc);
    removeSelectionOverlay(doc);
    removeSelectModeCursor(doc);
  }, [inSelectAndEditMode]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;

    const suppressedEvents = ["pointerdown", "mousedown", "mouseup", "submit"];

    const handleLoad = () => {
      const win = iframe.contentWindow;
      if (!win) return;
      // Intercept on the window in the capture phase: the window is the
      // first node in the propagation path, so this runs before any handler
      // the generated app registered, including capture-phase delegated
      // handlers on document (e.g. Bootstrap's data API).
      win.addEventListener("click", handleIframeClick, true);
      for (const type of suppressedEvents) {
        win.addEventListener(type, handleIframeInteraction, true);
      }
      win.addEventListener("mouseover", handleIframeMouseOver, true);
      win.addEventListener("mouseout", handleIframeMouseOut, true);
      win.addEventListener("scroll", handleIframeReposition, true);
      win.addEventListener("resize", handleIframeReposition);
      win.addEventListener("keydown", handleIframeKeyDown, true);
      win.document.addEventListener("click", handleIframeLinkClick);
      // A reload replaces the document, so re-apply mode side effects.
      if (inSelectAndEditModeRef.current) {
        applySelectModeCursor(win.document);
      }
    };

    iframe.addEventListener("load", handleLoad);
    // The current document may already be loaded (e.g. the component
    // re-rendered after the iframe's load event); attach to it directly.
    // addEventListener dedupes identical handlers, so this is safe.
    if (iframe.contentWindow?.document.readyState === "complete") {
      handleLoad();
    }

    return () => {
      iframe.removeEventListener("load", handleLoad);
      const win = iframe.contentWindow;
      if (win) {
        win.removeEventListener("click", handleIframeClick, true);
        for (const type of suppressedEvents) {
          win.removeEventListener(type, handleIframeInteraction, true);
        }
        win.removeEventListener("mouseover", handleIframeMouseOver, true);
        win.removeEventListener("mouseout", handleIframeMouseOut, true);
        win.removeEventListener("scroll", handleIframeReposition, true);
        win.removeEventListener("resize", handleIframeReposition);
        win.removeEventListener("keydown", handleIframeKeyDown, true);
        win.document.removeEventListener("click", handleIframeLinkClick);
      }
    };
  }, [
    iframeRef,
    handleIframeClick,
    handleIframeLinkClick,
    handleIframeInteraction,
    handleIframeMouseOver,
    handleIframeMouseOut,
    handleIframeReposition,
    handleIframeKeyDown,
  ]);
}
