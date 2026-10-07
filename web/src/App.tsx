import { NavLink, Route, Routes } from "react-router-dom";
import Overview from "./pages/Overview";
import Cases from "./pages/Cases";
import CaseDetail from "./pages/CaseDetail";
import Respondents from "./pages/Respondents";
import Laws from "./pages/Laws";
import Coverage from "./pages/Coverage";

export default function App() {
  return (
    <div className="shell">
      <nav className="side">
        <div className="brand">
          CNMV Enforcement
          <small>publicly observable ledger</small>
        </div>
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
