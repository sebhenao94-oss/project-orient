import { Navigate, Route, Routes } from "react-router-dom";
import "./App.css";
import { TabNav } from "./components/TabNav";
import { SessionBar } from "./components/SessionBar";
import { EquipmentView } from "./views/EquipmentView";
import { RelationshipsView } from "./views/RelationshipsView";
import { DiscrepanciesView } from "./views/DiscrepanciesView";
import { ZonesView } from "./views/ZonesView";
import { USE_MOCKS } from "./api/client";

function App() {
  return (
    <div className="app">
      <header className="app__bar">
        <div className="app__brand">
          <span className="app__logo">◆</span>
          <div>
            <h1>ORIENT · Review Agent</h1>
            <p className="muted small">
              Human review · property msa_orient_building_1 · Floor 02
              {USE_MOCKS && <span className="mock-pill">MOCK DATA</span>}
            </p>
          </div>
        </div>
        <SessionBar />
      </header>

      <TabNav />

      <main className="app__main">
        <Routes>
          <Route path="/" element={<Navigate to="/equipment" replace />} />
          <Route path="/equipment" element={<EquipmentView />} />
          <Route path="/relationships" element={<RelationshipsView />} />
          <Route path="/discrepancies" element={<DiscrepanciesView />} />
          <Route path="/zones" element={<ZonesView />} />
          <Route path="*" element={<Navigate to="/equipment" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;
