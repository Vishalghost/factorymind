import React from "react";
import ReactDOM from "react-dom/client";
import { RouterProvider, createRouter } from "@tanstack/react-router";
import { Amplify } from "aws-amplify";

import { routeTree } from "./routeTree.gen";
import "./styles.css";

// Configure Amplify with AppSync endpoint from environment.
// VITE_* vars are populated by scripts/deploy.sh from CloudFormation outputs.
Amplify.configure({
  API: {
    GraphQL: {
      endpoint: import.meta.env.VITE_APPSYNC_URL ?? "",
      region: import.meta.env.VITE_AWS_REGION ?? "us-east-1",
      defaultAuthMode: "apiKey",
      apiKey: import.meta.env.VITE_APPSYNC_API_KEY ?? "",
    },
  },
});

const router = createRouter({
  routeTree,
  // Defaults — no aggressive preload-stale-time (which was forcing route
  // chunks to be considered stale on every render and could trigger
  // re-fetch loops in production).
  scrollRestoration: true,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <RouterProvider router={router} />
  </React.StrictMode>,
);
