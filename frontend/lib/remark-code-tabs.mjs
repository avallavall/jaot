/**
 * Remark plugin that transforms <CodeTabs> with fenced code block children
 * into <CodeTabs tabs={[{language, code}]} /> with no children.
 *
 * This fixes the MDX issue where fenced code blocks inside JSX components
 * get hoisted out, leaving CodeTabs with no children to render as tabs.
 */
export function remarkCodeTabs() {
  return (tree) => {
    visitNode(tree);
  };
}

function visitNode(node) {
  if (!node.children) return;

  for (const child of node.children) {
    if (child.type === "mdxJsxFlowElement" && child.name === "CodeTabs") {
      transformCodeTabs(child);
    }
    visitNode(child);
  }
}

function transformCodeTabs(node) {
  const tabs = [];

  for (const child of node.children) {
    if (child.type === "code") {
      tabs.push({ language: child.lang || "text", code: child.value });
    }
  }

  if (tabs.length === 0) return;

  // Add tabs as an expression attribute: tabs={[{language, code}, ...]}
  node.attributes = [
    ...(node.attributes || []),
    {
      type: "mdxJsxAttribute",
      name: "tabs",
      value: {
        type: "mdxJsxAttributeValueExpression",
        value: JSON.stringify(tabs),
        data: {
          estree: {
            type: "Program",
            sourceType: "module",
            body: [
              {
                type: "ExpressionStatement",
                expression: buildTabsEstree(tabs),
              },
            ],
          },
        },
      },
    },
  ];

  // Clear children so MDX doesn't hoist them
  node.children = [];
}

function buildTabsEstree(tabs) {
  return {
    type: "ArrayExpression",
    elements: tabs.map((tab) => ({
      type: "ObjectExpression",
      properties: [
        {
          type: "Property",
          key: { type: "Identifier", name: "language" },
          value: { type: "Literal", value: tab.language },
          kind: "init",
          method: false,
          shorthand: false,
          computed: false,
        },
        {
          type: "Property",
          key: { type: "Identifier", name: "code" },
          value: { type: "Literal", value: tab.code },
          kind: "init",
          method: false,
          shorthand: false,
          computed: false,
        },
      ],
    })),
  };
}
