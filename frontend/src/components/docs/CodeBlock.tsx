"use client";

import { useState, useRef } from "react";
import { Check, Copy } from "lucide-react";
import { cn } from "@/lib/utils";

export function CodeBlock({ children, ...props }: React.HTMLAttributes<HTMLPreElement>) {
  const [copied, setCopied] = useState(false);
  const preRef = useRef<HTMLPreElement>(null);

  // Extract language from code child's className (e.g. "language-python")
  let language: string | undefined;
  if (children && typeof children === "object" && "props" in (children as React.ReactElement)) {
    const codeProps = (children as React.ReactElement).props as Record<string, unknown>;
    const className = codeProps?.className as string | undefined;
    const match = className?.match(/language-(\w+)/);
    if (match) language = match[1];
  }

  const handleCopy = async () => {
    const text = preRef.current?.textContent ?? "";
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="relative group" {...(language ? { "data-language": language } : {})}>
      <pre ref={preRef} {...props} className={cn("overflow-x-auto", props.className)}>
        {children}
      </pre>
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 p-1.5 rounded-md bg-muted/80 opacity-0 group-hover:opacity-100 transition-opacity"
        aria-label="Copy code"
      >
        {copied ? <Check className="h-4 w-4 text-green-500" /> : <Copy className="h-4 w-4" />}
      </button>
    </div>
  );
}
