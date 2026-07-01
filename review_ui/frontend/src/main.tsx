import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import "./index.css";
import App from "./App";
import { DataProvider } from "./session/DataContext";
import { SessionProvider } from "./session/SessionContext";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <DataProvider>
        <SessionProvider>
          <App />
        </SessionProvider>
      </DataProvider>
    </BrowserRouter>
  </StrictMode>,
);
