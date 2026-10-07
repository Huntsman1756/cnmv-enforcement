import { useEffect, useState } from "react";
import { api, type CoverageDoc } from "../lib/api";

export default function Coverage() {
  const [c, setC] = useState<CoverageDoc | null>(null);
  useEffect(() => {
    api.coverage().then(setC).catch(() =>
      setC({ scope_statement: "coverage ledger unavailable" })
    );
  }, []);
  if (!c) return <p className="faint">loading…</p>;
  return (
    <>
      <h1>Coverage ledger</h1>
      <p className="lede">{c.scope_statement}</p>
      {c.counts && (
        <div className="statgrid">
          <div className="card"><div className="v">{c.counts.cases}</div><div className="k">cases</div></div>
          <div className="card"><div className="v">{c.counts.infringements}</div><div className="k">infringements</div></div>
          <div className="card"><div className="v">{c.counts.sanctions}</div><div className="k">sanctions</div></div>
          <div className="card"><div className="v">{c.counts.respondents}</div><div className="k">respondents</div></div>
        </div>
      )}
      {c.sources && c.sources.length > 0 && (
        <>
          <h2>Sources</h2>
          <table className="data">
            <thead><tr><th>Source</th><th>Role</th><th>Window</th><th style={{ textAlign: "right" }}>Docs</th></tr></thead>
            <tbody>
              {c.sources.map((s, i) => (
                <tr key={i}>
                  <td className="mono">{s.source}</td>
                  <td className="small">{s.role}</td>
                  <td className="mono small">{s.observed_from ?? "?"} → {s.observed_to ?? "?"}</td>
                  <td className="num">{s.count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      <h2>Limitations</h2>
      <ul>
        {(c.limitations ?? []).map((l, i) => <li key={i} className="small" style={{ marginBottom: 5 }}>{l}</li>)}
      </ul>
      <h2>Explicit non-claims</h2>
      <ul>
        {(c.non_claims ?? []).map((l, i) => (
          <li key={i} className="small mono" style={{ marginBottom: 5 }}>{l}</li>
        ))}
      </ul>
      {c.known_gaps && c.known_gaps.length > 0 && (
        <>
          <h2>Known gaps</h2>
          <ul>{c.known_gaps.map((g, i) => <li key={i} className="small">{g}</li>)}</ul>
        </>
      )}
      {c.unresolved_or_ambiguous && c.unresolved_or_ambiguous.length > 0 && (
        <>
          <h2>Unresolved / ambiguous</h2>
          <ul>{c.unresolved_or_ambiguous.map((g, i) => <li key={i} className="small">{g}</li>)}</ul>
        </>
      )}
    </>
  );
}
