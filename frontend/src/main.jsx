import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import { initSentry } from "./lib/sentry.js";
import "./index.css";

// Initialize observability before rendering so any render-time errors
// are captured. No-op when VITE_SENTRY_DSN is unset.
initSentry();

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
