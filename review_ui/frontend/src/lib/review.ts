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
