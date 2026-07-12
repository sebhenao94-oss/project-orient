import { createContext } from "react";
import type { ActionInput } from "../api/client";
import type { ItemType, ReviewDecision, SessionVM } from "../types/viewModels";

export interface SessionContextValue {
  session: SessionVM | null;
  busy: boolean;
  error: string | null;
  clearError: () => void;
  decisionFor: (itemType: ItemType, itemKey: string) => ReviewDecision;
  isCommitted: (itemType: ItemType, itemKey: string) => boolean;
  decide: (input: ActionInput) => Promise<void>;
  clearDecision: (itemType: ItemType, itemKey: string) => Promise<boolean>;
  clearAll: () => Promise<void>;
  commit: () => Promise<void>;
  approved: number;
  rejected: number;
  decided: number;
  uncommitted: number;
  committedCount: number;
  totalReviewable: number;
}

export const SessionContext = createContext<SessionContextValue | null>(null);
