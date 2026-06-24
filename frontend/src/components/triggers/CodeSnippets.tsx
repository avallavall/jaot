"use client";

import { useState } from "react";
import { toast } from "sonner";
import { useTranslations } from "next-intl";
import type { OverrideField } from "@/lib/types";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Copy, Check } from "lucide-react";

interface CodeSnippetsProps {
  triggerId: string;
  triggerSecretPrefix: string;
  overrideSchema: OverrideField[] | null;
  webhookUrl: string;
}

function generateExampleOverrideData(schema: OverrideField[] | null): Record<string, unknown> {
  if (!schema || schema.length === 0) return {};
  const example: Record<string, unknown> = {};
  for (const field of schema) {
    if (field.default !== undefined) {
      example[field.name] = field.default;
    } else {
      switch (field.type) {
        case "string":
          example[field.name] = "example";
          break;
        case "number":
        case "integer":
          example[field.name] = 42;
          break;
        case "boolean":
          example[field.name] = true;
          break;
        case "array":
          example[field.name] = [];
          break;
        case "object":
          example[field.name] = {};
          break;
        default:
          example[field.name] = null;
      }
    }
  }
  return example;
}

function CodeBlock({ code, language, copyLabel }: { code: string; language: string; copyLabel: string }) {
  const [copied, setCopied] = useState(false);
  const t = useTranslations("triggers.codeSnippets");

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      toast.success(t("copiedClipboard"));
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error(t("copyError"));
    }
  };

  return (
    <div className="relative group">
      <pre className="bg-muted rounded-lg p-4 overflow-x-auto text-sm font-mono leading-relaxed">
        <code className={`language-${language}`}>{code}</code>
      </pre>
      <Button
        variant="ghost"
        size="sm"
        onClick={handleCopy}
        className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity h-8 w-8 p-0"
        title={copyLabel}
      >
        {copied ? (
          <Check className="w-4 h-4 text-green-500" />
        ) : (
          <Copy className="w-4 h-4" />
        )}
      </Button>
    </div>
  );
}

export function CodeSnippets({
  triggerId,
  triggerSecretPrefix,
  overrideSchema,
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  webhookUrl,
}: CodeSnippetsProps) {
  const t = useTranslations("triggers.codeSnippets");
  const baseUrl =
    typeof window !== "undefined"
      ? (process.env.NEXT_PUBLIC_API_URL ?? window.location.origin)
      : "https://jaot.io";

  const exampleData = generateExampleOverrideData(overrideSchema);
  const hasOverrides = Object.keys(exampleData).length > 0;
  const exampleJson = JSON.stringify({ override_data: exampleData }, null, 2);

  const curlSnippet = `curl -X POST "${baseUrl}/api/v2/triggers/${triggerId}/fire" \\
  -H "Authorization: Bearer <your-trigger-secret>" \\
  -H "Content-Type: application/json"${hasOverrides ? ` \\
  -d '${JSON.stringify({ override_data: exampleData })}'` : ""}`;

  const pythonSnippet = `import httpx

response = httpx.post(
    "${baseUrl}/api/v2/triggers/${triggerId}/fire",
    headers={
        "Authorization": "Bearer <your-trigger-secret>",
        "Content-Type": "application/json",
    },${hasOverrides ? `
    json=${JSON.stringify({ override_data: exampleData }, null, 4).replace(/\n/g, "\n    ")},` : ""}
)
print(response.json())`;

  const jsSnippet = `const response = await fetch("${baseUrl}/api/v2/triggers/${triggerId}/fire", {
  method: "POST",
  headers: {
    "Authorization": "Bearer <your-trigger-secret>",
    "Content-Type": "application/json",
  },${hasOverrides ? `
  body: JSON.stringify(${exampleJson}),` : ""}
});
const data = await response.json();
console.log(data.run_id);`;

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="font-semibold text-sm">{t("title")}</h3>
          <p className="text-xs text-muted-foreground mt-0.5">
            {t.rich("replaceSecret", { prefix: triggerSecretPrefix, code: (chunks) => <code>{chunks}</code> })}
          </p>
        </div>
      </div>

      <Tabs defaultValue="curl">
        <TabsList>
          <TabsTrigger value="curl">{t("curl")}</TabsTrigger>
          <TabsTrigger value="python">{t("python")}</TabsTrigger>
          <TabsTrigger value="javascript">{t("javascript")}</TabsTrigger>
        </TabsList>

        <TabsContent value="curl" className="mt-3">
          <CodeBlock code={curlSnippet} language="bash" copyLabel={t("copyToClipboard")} />
        </TabsContent>

        <TabsContent value="python" className="mt-3">
          <CodeBlock code={pythonSnippet} language="python" copyLabel={t("copyToClipboard")} />
        </TabsContent>

        <TabsContent value="javascript" className="mt-3">
          <CodeBlock code={jsSnippet} language="javascript" copyLabel={t("copyToClipboard")} />
        </TabsContent>
      </Tabs>

      {hasOverrides && (
        <p className="text-xs text-muted-foreground">
          {t.rich("overrideNote", { code: (chunks) => <code>{chunks}</code> })}
        </p>
      )}
    </div>
  );
}
