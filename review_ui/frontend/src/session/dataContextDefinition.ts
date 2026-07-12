import { createContext } from "react";
import type {
  DiscrepancyVM,
  EquipmentVM,
  RelationshipsVM,
  ZoneVM,
} from "../types/viewModels";

export interface DataContextValue {
  equipment: EquipmentVM[];
  zones: ZoneVM[];
  discrepancies: DiscrepancyVM[];
  relationships: RelationshipsVM | null;
  loading: boolean;
  error: string | null;
  /** Denominator for the session progress bar: every item that takes a decision. */
  totalReviewable: number;
  /** Canonical action identities; discrepancy rows deliberately add no keys. */
  reviewableKeys: ReadonlySet<string>;
}

export const DataContext = createContext<DataContextValue | null>(null);
