import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { NSFWProvider } from "./context/NSFWContext";
import { ToastProvider } from "./context/ToastContext";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <ToastProvider>
        <NSFWProvider>
          <App />
        </NSFWProvider>
      </ToastProvider>
    </BrowserRouter>
  </React.StrictMode>
);
