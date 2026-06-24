"use client";

import { useEffect } from "react";

const MARKER = "\u200B"; // zero-width space

/**
 * Global provider that detects zero-width space markers in DOM text nodes
 * (injected by getMessageFallback in request.ts for missing translations)
 * and wraps them with data-i18n-fallback spans for CSS styling.
 *
 * This approach requires zero changes to existing t() call sites.
 */
export function FallbackProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    let frameId: number | null = null;
    let pendingNodes: Element[] = [];

    function processNodes() {
      frameId = null;
      const nodes = pendingNodes;
      pendingNodes = [];
      for (const node of nodes) {
        scanForFallbacks(node);
      }
    }

    function scheduleProcess(node: Element) {
      pendingNodes.push(node);
      if (frameId === null) {
        frameId = requestAnimationFrame(processNodes);
      }
    }

    // Initial scan
    scanForFallbacks(document.body);

    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        for (const node of mutation.addedNodes) {
          if (node.nodeType === Node.ELEMENT_NODE) {
            scheduleProcess(node as Element);
          }
        }
      }
    });

    observer.observe(document.body, { childList: true, subtree: true });

    return () => {
      observer.disconnect();
      if (frameId !== null) {
        cancelAnimationFrame(frameId);
      }
    };
  }, []);

  return <>{children}</>;
}

function scanForFallbacks(root: Element) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node: Text | null;
  while ((node = walker.nextNode() as Text | null)) {
    const text = node.textContent ?? "";
    if (text.startsWith(MARKER) && text.endsWith(MARKER) && text.length > 2) {
      const parent = node.parentElement;
      if (parent && !parent.hasAttribute("data-i18n-fallback")) {
        const span = document.createElement("span");
        span.setAttribute("data-i18n-fallback", "");
        span.textContent = text.slice(1, -1); // strip markers
        node.replaceWith(span);
      }
    }
  }
}
