import type { ReactNode } from "react";

interface TooLargeNoticeProps {
  /** A lucide icon already sized (e.g. `className="mx-auto mb-3 h-8 w-8 text-muted-foreground"`). */
  icon: ReactNode;
  title: string;
  body: string;
  testid: string;
}

/**
 * The "this model is too big for a visual representation" empty state, shared by
 * the canvas (BuildPanel) and the text-editor (ModelEditorPanel) lenses — the model
 * is still fully analyzable/solvable from its canonical form.
 */
export function TooLargeNotice({ icon, title, body, testid }: TooLargeNoticeProps) {
  return (
    <div data-testid={testid} className="flex-1 flex items-center justify-center p-6">
      <div className="max-w-md text-center">
        {icon}
        <p className="text-sm font-medium">{title}</p>
        <p className="mt-1 text-sm text-muted-foreground">{body}</p>
      </div>
    </div>
  );
}
