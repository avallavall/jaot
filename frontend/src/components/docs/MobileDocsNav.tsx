"use client";

import { useState } from "react";
import { Menu, X } from "lucide-react";
import { Dialog } from "radix-ui";
import { DocsSidebar } from "./DocsSidebar";

export function MobileDocsNav() {
  const [open, setOpen] = useState(false);

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button
          className="lg:hidden fixed bottom-4 right-4 z-50 p-3 rounded-full bg-primary text-primary-foreground shadow-lg"
          aria-label="Open documentation navigation"
        >
          <Menu className="h-5 w-5" />
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/50" />
        <Dialog.Content className="fixed inset-y-0 left-0 z-50 w-80 max-w-[85vw] bg-background shadow-xl overflow-y-auto">
          <div className="flex items-center justify-between p-4 border-b border-border">
            <Dialog.Title className="text-sm font-semibold">Documentation</Dialog.Title>
            <Dialog.Close asChild>
              <button className="p-1 rounded-md hover:bg-muted" aria-label="Close navigation">
                <X className="h-4 w-4" />
              </button>
            </Dialog.Close>
          </div>
          <DocsSidebar onNavigate={() => setOpen(false)} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
