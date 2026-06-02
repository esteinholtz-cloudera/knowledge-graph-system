import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Benchmark } from "./pages/Benchmark";
import { Dashboard } from "./pages/Dashboard";
import { Normalize } from "./pages/Normalize";
import { Ontology } from "./pages/Ontology";
import { Process } from "./pages/Process";
import "./App.css";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="process" element={<Process />} />
          <Route path="ontology" element={<Ontology />} />
          <Route path="normalize" element={<Normalize />} />
          <Route path="benchmark" element={<Benchmark />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
