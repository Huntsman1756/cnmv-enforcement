import { useEffect, useState } from "react";
import { api, eur, type Stats } from "../lib/api";
import Bars from "../components/Bars";

export default function Overview() {
  const [s, setS] = useState<Stats | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.stats().then(setS).catch((e) => setErr(String(e)));
  }, []);
  if (err)
    return (
      <div className="notice">
        <strong>API unreachable:</strong> {err}. Start the dataset API (
        <code>uvicorn cnmv_enforcement.api.app:app --port 8765</code>) and run{" "}
        <code>cnmv-enforcement build</code> first.
      </div>
    );
  if (!s) return <p className="faint">loading…</p>;
  return (
    <>
      <h1>Publicly observable CNMV enforcement</h1>
      <p className="lede">
        An evidence-backed historical ledger reconstructed from the CNMV
        public sanctions register, BOE publications and subsequent official
        documents. This is <strong>not</strong> a complete database of all
        CNMV sanctions — absence from this dataset does not establish that no
        sanction was imposed.
      </p>
      <div className="statgrid">
        <div className="card"><div className="v">{s.cases}</div><div className="k">cases</div></div>
        <div className="card"><div className="v">{s.infringements}</div><div className="k">infringements</div></div>
        <div className="card"><div className="v">{s.sanctions}</div><div className="k">sanctions</div></div>
        <div className="card"><div className="v">{s.respondents}</div><div className="k">respondents</div></div>
        <div className="card"><div className="v">{eur(s.total_fine_eur)}</div><div className="k">total fines observed</div></div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14 }}>
        <div className="panel">
          <Bars
            label="By severity"
            rows={s.by_severity.map((x) => ({
              label: x.severity === "VERY_SERIOUS" ? "muy grave" : x.severity === "SERIOUS" ? "grave" : x.severity,
              value: x.n,
            }))}
          />
        </div>
        <div className="panel">
          <Bars
            label="By sanction type"
            rows={s.by_sanction_type.map((x) => ({
              label: x.sanction_type,
              value: x.n,
              hint: x.total ? eur(x.total) : undefined,
            }))}
          />
        </div>
        <div className="panel">
          <Bars
            label="By statute"
            rows={s.by_statute.slice(0, 8).map((x) => ({
              label: x.statute_normalized,
              value: x.n,
            }))}
          />
        </div>
      </div>
      <div className="notice">
        <strong>Scope:</strong> the CNMV public register retains entries for
        five years and covers very serious and serious infringements; minor
        infringements are not guaranteed. Historical backfill is a separate
        versioned extension. See <a href="#/coverage">Coverage</a> for the
        full ledger of sources, windows and non-claims.
      </div>
    </>
  );
}
