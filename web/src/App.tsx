import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api, type Meta } from "./lib/api";
import Overview from "./pages/Overview";
import Cases from "./pages/Cases";
import CaseDetail from "./pages/CaseDetail";
import Respondents from "./pages/Respondents";
import Laws from "./pages/Laws";
import Coverage from "./pages/Coverage";

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  useEffect(() => {
    api.metadata().then(setMeta).catch(() => setMeta(null));
  }, []);
  return (
    <div className="shell">
      <nav className="side">
        <div className="brand">
          CNMV Enforcement
          <small>publicly observable ledger</small>
        </div>
        {meta?.dataset_release && (
          <small className="faint" title={`corpus ${meta.corpus_logical_sha256?.slice(0, 16)}…`}>
            dataset {meta.dataset_release}
          </small>
        )}
        <NavLink to="/" end>Overview</NavLink>
        <NavLink to="/cases">Cases</NavLink>
        <NavLink to="/respondents">Respondents</NavLink>
        <NavLink to="/laws">Legal basis</NavLink>
        <NavLink to="/coverage">Coverage</NavLink>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/cases" element={<Cases />} />
          <Route path="/cases/:id" element={<CaseDetail />} />
          <Route path="/respondents" element={<Respondents />} />
          <Route path="/laws" element={<Laws />} />
          <Route path="/coverage" element={<Coverage />} />
        </Routes>
      </main>
    </div>
  );
}
