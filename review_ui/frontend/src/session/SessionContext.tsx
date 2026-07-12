// Review-session state shared by every view.
//
// Commit model (W6 decision): FLUSH-AND-CONTINUE. Commit writes the current
// batch of decisions to the production DB (one transaction), locks those items,
// and re-opens a fresh session so undecided items stay actionable — the engineer
// keeps triaging and commits again in batches. Committed items are frozen;
// undecided items are not.

import {
  useCallback,
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
import { SessionContext, type SessionContextValue } from "./sessionContextDefinition";
import { useData } from "./useData";

const ACTION_TO_DECISION: Record<ActionInput["action"], ReviewDecision> = {
  approve: "approved",
  edit: "edited",
  reject: "rejected",
};

function messageFor(operation: string, cause: unknown): string {
  return `${operation} failed: ${cause instanceof Error ? cause.message : String(cause)}`;
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const { reviewableKeys } = useData();
  const [session, setSession] = useState<SessionVM | null>(null);
  const [decisions, setDecisions] = useState<Map<string, ReviewDecision>>(new Map());
  const [committed, setCommitted] = useState<Map<string, ReviewDecision>>(new Map());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    openSession("reviewer@joulea")
      .then((s) => !cancelled && setSession(s))
      .catch((e: unknown) => !cancelled && setError(messageFor("Opening the review session", e)));
    return () => {
      cancelled = true;
    };
  }, []);

  const decide = useCallback(
    async (input: ActionInput) => {
      if (!session) {
        setError("Cannot record a decision until the review session is open.");
        return;
      }
      const key = decisionKey(input.itemType, input.itemKey);
      if (committed.has(key)) return; // frozen once committed
      setBusy(true);
      setError(null);
      try {
        const next = await recordAction(session.sessionId, input);
        setSession(next);
        setDecisions((prev) => new Map(prev).set(key, ACTION_TO_DECISION[input.action]));
      } catch (e: unknown) {
        setError(messageFor("Recording the decision", e));
      } finally {
        setBusy(false);
      }
    },
    [session, committed],
  );

  // Revert a single *uncommitted* decision back to pending. Committed items are
  // frozen (already flushed to the DB) and cannot be cleared.
  const clearDecision = useCallback(
    async (itemType: ItemType, itemKey: string) => {
      const key = decisionKey(itemType, itemKey);
      if (!session) {
        setError("Cannot clear a decision until the review session is open.");
        return false;
      }
      if (committed.has(key)) {
        setError("Committed decisions are frozen and cannot be cleared.");
        return false;
      }
      setBusy(true);
      setError(null);
      try {
        const next = await clearAction(session.sessionId, itemType, itemKey);
        setSession(next);
        setDecisions((prev) => {
          const updated = new Map(prev);
          updated.delete(key);
          return updated;
        });
        return true;
      } catch (e: unknown) {
        setError(messageFor("Clearing the decision", e));
        return false;
      } finally {
        setBusy(false);
      }
    },
    [session, committed],
  );

  // Drop every uncommitted decision in the current batch. Committed items stay.
  const clearAll = useCallback(async () => {
    if (!session || decisions.size === 0) return;
    setBusy(true);
    setError(null);
    try {
      const next = await clearAllActions(session.sessionId);
      setSession(next);
      setDecisions(new Map());
    } catch (e: unknown) {
      setError(messageFor("Clearing the current batch", e));
    } finally {
      setBusy(false);
    }
  }, [session, decisions]);

  const commit = useCallback(async () => {
    if (!session || decisions.size === 0) return;
    setBusy(true);
    setError(null);
    try {
      await commitSession(session.sessionId); // flush this batch to production
      setCommitted((prev) => {
        const m = new Map(prev);
        for (const [k, v] of decisions) m.set(k, v);
        return m;
      });
      setDecisions(new Map());
      setSession(await openSession("reviewer@joulea")); // continue in a fresh session
    } catch (e: unknown) {
      setError(messageFor("Committing the current batch", e));
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

  const totalReviewable = useMemo(() => {
    const keys = new Set(reviewableKeys);
    for (const key of committed.keys()) keys.add(key);
    for (const key of decisions.keys()) keys.add(key);
    const serverTotal = session
      ? session.nPending + session.nApproved + session.nRejected
      : 0;
    return Math.max(keys.size, serverTotal);
  }, [reviewableKeys, committed, decisions, session]);

  const value: SessionContextValue = {
    session,
    busy,
    error,
    clearError: () => setError(null),
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
    totalReviewable,
  };

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
