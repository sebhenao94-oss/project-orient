import { NavLink } from "react-router-dom";

const TABS = [
  { to: "/equipment", label: "Equipment" },
  { to: "/relationships", label: "Relationships" },
  { to: "/discrepancies", label: "Discrepancies" },
  { to: "/zones", label: "Zones" },
];

export function TabNav() {
  return (
    <nav className="tabs">
      {TABS.map((t) => (
        <NavLink
          key={t.to}
          to={t.to}
          className={({ isActive }) => `tab${isActive ? " tab--active" : ""}`}
        >
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}
