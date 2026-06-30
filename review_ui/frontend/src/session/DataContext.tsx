// Loads the four review datasets once at app start and shares them, so views
// stay thin and the session progress bar has a real denominator.

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
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

interface DataContextValue {
  equipment: EquipmentVM[];
  zones: ZoneVM[];
  discrepancies: DiscrepancyVM[];
  relationships: RelationshipsVM | null;
  loading: boolean;
  error: string | null;
  /** Denominator for the session progress bar: every item that takes a decision. */
  totalReviewable: number;
}

const DataContext = createContext<DataContextValue | null>(null);

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

  const totalReviewable = useMemo(
    () =>
      equipment.length +
      discrepancies.length +
      zones.length +
      (relationships?.edges.length ?? 0),
    [equipment, discrepancies, zones, relationships],
  );

  const value: DataContextValue = {
    equipment,
    zones,
    discrepancies,
    relationships,
    loading,
    error,
    totalReviewable,
  };

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>;
}

export function useData(): DataContextValue {
  const ctx = useContext(DataContext);
  if (!ctx) throw new Error("useData must be used within a DataProvider");
  return ctx;
}
