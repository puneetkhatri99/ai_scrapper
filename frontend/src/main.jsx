import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { useStore } from "./store";
import "./style.css";

// The theme lives on <html>, not in React. Applied here, before render, so a
// reload into the dark theme never flashes light first -- persist rehydrates
// from localStorage synchronously, so the stored choice is already in the
// store by the time this line runs. The subscription then keeps the attribute
// in step with the switch, without a component re-rendering to do it.
const applyTheme = (theme) => {
  document.documentElement.dataset.theme = theme;
};

applyTheme(useStore.getState().theme);
useStore.subscribe((s, prev) => s.theme !== prev.theme && applyTheme(s.theme));

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
