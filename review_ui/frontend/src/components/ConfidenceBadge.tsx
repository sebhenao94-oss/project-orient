import { formatConfidence, isLowConfidence } from "../lib/review";

/** Confidence pill; low-confidence (<0.75) gets a visual flag. */
export function ConfidenceBadge({ confidence }: { confidence: number | null }) {
  const low = isLowConfidence(confidence);
  const none = confidence === null;
  const cls = none ? "conf conf--none" : low ? "conf conf--low" : "conf conf--ok";
  return (
    <span className={cls} title={low ? "Below 0.75 — needs review" : undefined}>
      {low && <span aria-hidden>⚠ </span>}
      {formatConfidence(confidence)}
    </span>
  );
}
