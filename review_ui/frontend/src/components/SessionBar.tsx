import { useSession } from "../session/useSession";

/** Session progress bar (approved / pending / rejected) + the batch commit gate. */
export function SessionBar() {
  const {
    session, approved, rejected, decided, uncommitted, committedCount,
    commit, clearAll, busy, error, clearError, totalReviewable,
  } = useSession();

  const pending = Math.max(0, totalReviewable - decided);
  const pct = (n: number) => (totalReviewable > 0 ? (n / totalReviewable) * 100 : 0);

  const onCommit = () => {
    if (uncommitted === 0) return;
    if (window.confirm(`Commit ${uncommitted} decision(s) to the production database?`)) {
      void commit();
    }
  };

  const onClearAll = () => {
    if (uncommitted === 0) return;
    if (window.confirm(`Clear ${uncommitted} uncommitted decision(s)? Committed items are unaffected.`)) {
      void clearAll();
    }
  };

  return (
    <div className="sessionbar">
      {error && (
        <div className="sessionbar__error" role="alert">
          <span>{error}</span>
          <button className="btn btn--error-close" onClick={clearError} aria-label="Dismiss error">×</button>
        </div>
      )}
      <div className="sessionbar__meta">
        <span className="sessionbar__title">Review session</span>
        <span className="pill pill--open">open</span>
        {session && <code className="sessionbar__id">{session.sessionId.slice(0, 8)}</code>}
        {committedCount > 0 && <span className="pill pill--committed">{committedCount} committed</span>}
      </div>

      <div className="progress" role="img" aria-label="session progress">
        <div className="progress__seg progress__seg--approved" style={{ width: `${pct(approved)}%` }} />
        <div className="progress__seg progress__seg--rejected" style={{ width: `${pct(rejected)}%` }} />
        <div className="progress__seg progress__seg--pending" style={{ width: `${pct(pending)}%` }} />
      </div>

      <div className="sessionbar__counts">
        <span className="count count--approved">{approved} approved</span>
        <span className="count count--pending">{pending} pending</span>
        <span className="count count--rejected">{rejected} rejected</span>
      </div>

      <button className="btn btn--clear-all" disabled={busy || uncommitted === 0} onClick={onClearAll}>
        Clear all
      </button>
      <button className="btn btn--commit" disabled={busy || uncommitted === 0} onClick={onCommit}>
        {uncommitted > 0 ? `Commit ${uncommitted}` : "Commit session"}
      </button>
    </div>
  );
}
