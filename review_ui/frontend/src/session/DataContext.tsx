// Loads the four review datasets once at app start and shares them, so views
// stay thin and the session progress bar has a real denominator.

import {
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  decisionKey,
  listDiscrepancies,
  listEquipment,
  listRelationships,
  listZones,
} from "../api/client";
import type {
  DiscrepancyVM,
  EquipmentVM,
  RelationshipsVM,
  ZoneVM,
} from "../types/viewModels";
import { DataContext, type DataContextValue } from "./dataContextDefinition";

export function DataProvider({ children }: { children: ReactNode }) {
  const [equipment, setEquipment] = useState<EquipmentVM[]>([]);
  const [zones, setZones] = useState<ZoneVM[]>([]);
  const [discrepancies, setDiscrepancies] = useState<DiscrepancyVM[]>([]);
  const [relationships, setRelationships] = useState<RelationshipsVM | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listEquipment(), listZones(), listDiscrepancies(), listRelationships()])
      .then(([eq, zo, di, re]) => {
        if (cancelled) return;
        setEquipment(eq);
        setZones(zo);
        setDiscrepancies(di);
        setRelationships(re);
      })
      .catch((e: unknown) => !cancelled && setError(String(e)))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  const reviewableKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const item of equipment) {
      if (item.status !== "floor_ambiguous") {
        keys.add(decisionKey("equipment", item.key));
      }
    }
    for (const edge of relationships?.edges ?? []) {
      keys.add(decisionKey("relationship", edge.key));
    }
    for (const zone of zones) keys.add(decisionKey("zone", zone.key));
    return keys;
  }, [equipment, zones, relationships]);
  const totalReviewable = reviewableKeys.size;

  const value: DataContextValue = {
    equipment,
    zones,
    discrepancies,
    relationships,
    loading,
    error,
    totalReviewable,
    reviewableKeys,
  };

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>;
}
