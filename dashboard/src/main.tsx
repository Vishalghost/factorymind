import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Amplify } from "aws-amplify";

import App from "./App";
import { PlantOverview } from "./pages/PlantOverview";
import { MachineDetail } from "./pages/MachineDetail";
import { Alerts } from "./pages/Alerts";
import { WorkOrders } from "./pages/WorkOrders";
import { Sustainability } from "./pages/Sustainability";

import "./styles.css";

// Configure Amplify with AppSync endpoint from environment.
// These VITE_* vars are populated by deploy.sh from CloudFormation outputs.
Amplify.configure({
  API: {
    GraphQL: {
      endpoint: import.meta.env.VITE_APPSYNC_URL ?? "",
      region: import.meta.env.VITE_AWS_REGION ?? "ap-south-1",
      defaultAuthMode: "apiKey",
      apiKey: import.meta.env.VITE_APPSYNC_API_KEY ?? "",
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />}>
          <Route index element={<Navigate to="/plant" replace />} />
          <Route path="plant" element={<PlantOverview />} />
          <Route path="machines/:machineId" element={<MachineDetail />} />
          <Route path="alerts" element={<Alerts />} />
          <Route path="work-orders" element={<WorkOrders />} />
          <Route path="sustainability" element={<Sustainability />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
