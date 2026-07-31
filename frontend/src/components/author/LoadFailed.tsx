"use client";

import { AlertCircle } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";

/**
 * Shown when a panel could not load. Deliberately distinct from the empty
 * states: "you haven't published anything yet" is a claim about the author's
 * work, and rendering it because a request failed makes the app lie about them.
 */
export function LoadFailed({ message }: { message: string }) {
  return (
    <Card>
      <CardContent className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
        <AlertCircle className="h-4 w-4" />
        <p>{message}</p>
      </CardContent>
    </Card>
  );
}
