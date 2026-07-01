import { formatConfidence, isLowConfidence } from "../lib/review";

/**
 * Confidence pill. Low-confidence (<0.75) gets a visual flag. When there is no
 * score (null) but the item is otherwise flagged (review_required), show a
 * "review" flag instead of a bare "—" so the engineer's eye still lands on it.
 */
export function ConfidenceBadge({
  confidence,
  flagged = false,
}: {
  confidence: number | null;
  flagged?: boolean;
}) {
  const low = isLowConfidence(confidence);
  const none = confidence === null;

  if (none && flagged) {
    return (
      <span className="conf conf--review" title="Flagged for review (no confidence score)">
        ⚠ review
      </span>
    );
  }

  const cls = none ? "conf conf--none" : low ? "conf conf--low" : "conf conf--ok";
  return (
    <span className={cls} title={low ? "Below 0.75 — needs review" : undefined}>
      {low && <span aria-hidden>⚠ </span>}
      {formatConfidence(confidence)}
    </span>
  );
}
