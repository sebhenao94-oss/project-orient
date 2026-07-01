// Shared review conventions from the brief: the 0.75 confidence threshold and
// the default confidence-ascending sort (low-confidence first so the engineer's
// eye goes there).

export const REVIEW_THRESHOLD = 0.75;

export function isLowConfidence(confidence: number | null): boolean {
  return confidence !== null && confidence < REVIEW_THRESHOLD;
}

export function formatConfidence(confidence: number | null): string {
  return confidence === null ? "—" : `${Math.round(confidence * 100)}%`;
}

/**
 * Sort by confidence ascending. Known-but-low values sort first; items with no
 * score (null) sort last, since "unknown" is not the same urgent signal as a
 * concrete low score.
 */
export function byConfidenceAsc<T extends { confidence: number | null }>(
  a: T,
  b: T,
): number {
  if (a.confidence === null && b.confidence === null) return 0;
  if (a.confidence === null) return 1;
  if (b.confidence === null) return -1;
  return a.confidence - b.confidence;
}

/**
 * An item "needs attention" if it has a low confidence score OR — when the
 * pipeline emitted no score (the common case on real W4 data, where confidence
 * is uncalibrated and left null) — it is flagged review_required. This keeps the
 * brief's "eye goes to the risky items first" intent alive when scores are absent.
 */
export function needsAttention(item: {
  confidence: number | null;
  reviewRequired?: boolean;
}): boolean {
  return isLowConfidence(item.confidence) || item.reviewRequired === true;
}

/** Attention-first, then confidence-ascending. Falls back to review_required. */
export function byAttentionThenConfidence<
  T extends { confidence: number | null; reviewRequired?: boolean },
>(a: T, b: T): number {
  const af = needsAttention(a);
  const bf = needsAttention(b);
  if (af !== bf) return af ? -1 : 1;
  return byConfidenceAsc(a, b);
}

/** Severity ordering for discrepancies (high first). */
export const SEVERITY_RANK: Record<string, number> = { high: 0, medium: 1, low: 2 };
