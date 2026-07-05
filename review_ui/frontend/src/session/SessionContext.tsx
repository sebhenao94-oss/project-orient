// Review-session state shared by every view.
//
// Commit model (W6 decision): FLUSH-AND-CONTINUE. Commit writes the current
// batch of decisions to the production DB (one transaction), locks those items,
// and re-opens a fresh session so undecided items stay actionable — the engineer
// keeps triaging and commits again in batches. Committed items are frozen;
// undecided items are not.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  clearAction,
  clearAllActions,
  commitSession,
  decisionKey,
  openSession,
  recordAction,
  type ActionInput,
} from "../api/client";
import type { ItemType, ReviewDecision, SessionVM } from "../types/viewModels";

const ACTION_TO_DECISION: Record<ActionInput["action"], ReviewDecision> = {
  approve: "approved",
  edit: "edited",
  reject: "rejected",
};

interface SessionContextValue {
  session: SessionVM | null;
  busy: boolean;
  decisionFor: (itemType: ItemType, itemKey: string) => ReviewDecision;
  isCommitted: (itemType: ItemType, itemKey: string) => boolean;
  decide: (input: ActionInput) => Promise<void>;
  clearDecision: (itemType: ItemType, itemKey: string) => void;
  clearAll: () => void;
  commit: () => Promise<void>;
  approved: number; // cumulative (committed + current batch)
  rejected: number;
  decided: number; // total items with any decision
  uncommitted: number; // current-batch decisions awaiting commit
  committedCount: number;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<SessionVM | null>(null);
  const [decisions, setDecisions] = useState<Map<string, ReviewDecision>>(new Map());
  const [committed, setCommitted] = useState<Map<string, ReviewDecision>>(new Map());
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    openSession("reviewer@joulea")
      .then((s) => !cancelled && setSession(s))
      .catch((e) => console.error("openSession failed", e));
    return () => {
      cancelled = true;
    };
  }, []);

  const decide = useCallback(
    async (input: ActionInput) => {
      if (!session) return;
      const key = decisionKey(input.itemType, input.itemKey);
      if (committed.has(key)) return; // frozen once committed
      setBusy(true);
      try {
        const next = await recordAction(session.sessionId, input);
        setSession(next);
        setDecisions((prev) => new Map(prev).set(key, ACTION_TO_DECISION[input.action]));
      } catch (e) {
        console.error("recordAction failed", e);
      } finally {
        setBusy(false);
      }
    },
    [session, committed],
  );

  // Revert a single *uncommitted* decision back to pending. Committed items are
  // frozen (already flushed to the DB) and cannot be cleared.
  const clearDecision = useCallback(
    (itemType: ItemType, itemKey: string) => {
      const key = decisionKey(itemType, itemKey);
      if (committed.has(key)) return;
      setDecisions((prev) => {
        if (!prev.has(key)) return prev;
        const m = new Map(prev);
        m.delete(key);
        return m;
      });
      if (session) {
        clearAction(session.sessionId, itemType, itemKey)
          .then(setSession)
          .catch((e) => console.error("clearAction failed", e));
      }
    },
    [session, committed],
  );

  // Drop every uncommitted decision in the current batch. Committed items stay.
  const clearAll = useCallback(() => {
    setDecisions(new Map());
    if (session) {
      clearAllActions(session.sessionId)
        .then(setSession)
        .catch((e) => console.error("clearAllActions failed", e));
    }
  }, [session]);

  const commit = useCallback(async () => {
    if (!session || decisions.size === 0) return;
    setBusy(true);
    try {
      await commitSession(session.sessionId); // flush this batch to production
      setCommitted((prev) => {
        const m = new Map(prev);
        for (const [k, v] of decisions) m.set(k, v);
        return m;
      });
      setDecisions(new Map());
      setSession(await openSession("reviewer@joulea")); // continue in a fresh session
    } catch (e) {
      console.error("commit failed", e);
    } finally {
      setBusy(false);
    }
  }, [session, decisions]);

  const decisionFor = useCallback(
    (itemType: ItemType, itemKey: string): ReviewDecision => {
      const k = decisionKey(itemType, itemKey);
      return committed.get(k) ?? decisions.get(k) ?? "pending";
    },
    [committed, decisions],
  );

  const isCommitted = useCallback(
    (itemType: ItemType, itemKey: string): boolean =>
      committed.has(decisionKey(itemType, itemKey)),
    [committed],
  );

  const { approved, rejected } = useMemo(() => {
    let a = 0;
    let r = 0;
    for (const d of [...committed.values(), ...decisions.values()]) {
      if (d === "rejected") r += 1;
      else if (d === "approved" || d === "edited") a += 1;
    }
    return { approved: a, rejected: r };
  }, [committed, decisions]);

  const value: SessionContextValue = {
    session,
    busy,
    decisionFor,
    isCommitted,
    decide,
    clearDecision,
    clearAll,
    commit,
    approved,
    rejected,
    decided: committed.size + decisions.size,
    uncommitted: decisions.size,
    committedCount: committed.size,
  };

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within a SessionProvider");
  return ctx;
}
