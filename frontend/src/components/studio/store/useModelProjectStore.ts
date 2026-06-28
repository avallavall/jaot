"use client";

import { createContext, useContext } from "react";
import { useStore } from "zustand";
import type { ModelProjectState, ModelProjectStore } from "./createModelProjectStore";

export const ModelProjectStoreContext = createContext<ModelProjectStore | null>(null);

/** Subscribe to a slice of the canonical model store. */
export function useModelProjectStore<T>(selector: (state: ModelProjectState) => T): T {
  const store = useContext(ModelProjectStoreContext);
  if (!store) {
    throw new Error("useModelProjectStore must be used within a ModelProjectStoreProvider");
  }
  return useStore(store, selector);
}

/** Imperative access to the store (getState/setState/subscribe) for bridges and hooks. */
export function useModelProjectStoreApi(): ModelProjectStore {
  const store = useContext(ModelProjectStoreContext);
  if (!store) {
    throw new Error("useModelProjectStoreApi must be used within a ModelProjectStoreProvider");
  }
  return store;
}
