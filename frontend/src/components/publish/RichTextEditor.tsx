"use client";

import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "@tiptap/markdown";
import { Table } from "@tiptap/extension-table";
import { TableRow } from "@tiptap/extension-table-row";
import { TableCell } from "@tiptap/extension-table-cell";
import { TableHeader } from "@tiptap/extension-table-header";
import { TaskList } from "@tiptap/extension-task-list";
import { TaskItem } from "@tiptap/extension-task-item";
import { Highlight } from "@tiptap/extension-highlight";
import { Link } from "@tiptap/extension-link";
import { Placeholder } from "@tiptap/extension-placeholder";
import { EditorToolbar } from "./EditorToolbar";
import { cn } from "@/lib/utils";

interface RichTextEditorProps {
  content: string;
  onChange: (markdown: string) => void;
  placeholder?: string;
  label?: string;
  className?: string;
}

export function RichTextEditor({
  content,
  onChange,
  placeholder,
  label,
  className,
}: RichTextEditorProps) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3] },
      }),
      Markdown,
      Table.configure({ resizable: true }),
      TableRow,
      TableCell,
      TableHeader,
      TaskList,
      TaskItem.configure({ nested: true }),
      Highlight,
      Link.configure({
        openOnClick: false,
        HTMLAttributes: {
          class: "text-primary underline",
        },
      }),
      Placeholder.configure({
        placeholder: placeholder || "Start writing...",
      }),
    ],
    content,
    contentType: "markdown",
    onUpdate: ({ editor: ed }) => {
      onChange(ed.getMarkdown());
    },
    editorProps: {
      attributes: {
        class: "outline-none min-h-[130px]",
      },
    },
  });

  return (
    <div className={cn("border rounded-md overflow-hidden", className)}>
      {label && (
        <label className="block text-sm font-medium px-4 pt-3 pb-1">{label}</label>
      )}
      <EditorToolbar editor={editor} />
      <EditorContent
        editor={editor}
        className="prose dark:prose-invert max-w-none p-4 min-h-[150px] focus-within:outline-none [&_.ProseMirror]:outline-none [&_.ProseMirror]:min-h-[130px] [&_.ProseMirror_p.is-editor-empty:first-child::before]:text-muted-foreground [&_.ProseMirror_p.is-editor-empty:first-child::before]:float-left [&_.ProseMirror_p.is-editor-empty:first-child::before]:content-[attr(data-placeholder)] [&_.ProseMirror_p.is-editor-empty:first-child::before]:pointer-events-none [&_.ProseMirror_p.is-editor-empty:first-child::before]:h-0"
      />
    </div>
  );
}
