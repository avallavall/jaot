import type { MDXComponents } from "mdx/types";
import { CodeBlock } from "@/components/docs/CodeBlock";
import { CodeTabs } from "@/components/docs/CodeTabs";
import { Callout } from "@/components/docs/Callout";
import Link from "next/link";

export function useMDXComponents(): MDXComponents {
  return {
    pre: (props) => <CodeBlock {...props} />,
    CodeTabs,
    Callout,
    a: ({ href, children, ...props }) => {
      if (href?.startsWith("/") || href?.startsWith("#")) {
        return (
          <Link href={href} {...props}>
            {children}
          </Link>
        );
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
          {children}
        </a>
      );
    },
  };
}
