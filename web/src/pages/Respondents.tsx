import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, eur, type Respondent } from "../lib/api";

export default function Respondents() {
  const [sp, setSp] = useSearchParams();
  const q = sp.get("q") ?? "";
  const [rows, setRows] = useState<Respondent[] | null>(null);
  useEffect(() => {
    api.respondents(q || undefined).then((r) => setRows(r.respondents));
  }, [q]);
  return (
    <>
      <h1>Respondents</h1>
      <p className="lede">
        Sanctioned parties as named in the official publications. Names are
        reproduced as published — no enrichment or reidentification is
        applied.
      </p>
      <div className="filters">
        <input
          placeholder="search name…"
          value={q}
          onChange={(e) => {
            const next = new URLSearchParams(sp);
            e.target.value ? next.set("q", e.target.value) : next.delete("q");
            setSp(next);
          }}
        />
      </div>
      {!rows && <p className="faint">loading…</p>}
      {rows && (
        <table className="data">
          <thead>
            <tr><th>Name</th><th>Type</th><th style={{ textAlign: "right" }}>Sanctions</th><th style={{ textAlign: "right" }}>Cases</th><th style={{ textAlign: "right" }}>Total fines</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.respondent_id}>
                <td className="small">
                  {r.normalized_name ?? r.raw_display_name}
                  {r.source_anonymized && <span className="tag dim" style={{ marginLeft: 8 }}>anonymized</span>}
                </td>
                <td className="small">{r.respondent_type}</td>
                <td className="num">{r.sanctions ?? 0}</td>
                <td className="num">{r.cases ?? 0}</td>
                <td className="num">{eur(r.total_amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
