import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, type CaseRow } from "../lib/api";
import { FirmnessTag } from "../components/Tags";

export default function Cases() {
  const [sp, setSp] = useSearchParams();
  const [rows, setRows] = useState<CaseRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const severity = sp.get("severity") ?? "";
  const statute = sp.get("statute") ?? "";
  const respondent = sp.get("respondent") ?? "";

  useEffect(() => {
    setRows(null);
    api
      .cases({
        severity: severity || undefined,
        statute: statute || undefined,
        respondent: respondent || undefined,
        limit: 200,
      })
      .then((r) => setRows(r.cases))
      .catch((e) => setErr(String(e)));
  }, [severity, statute, respondent]);

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(sp);
    v ? next.set(k, v) : next.delete(k);
    setSp(next);
  };

  return (
    <>
      <h1>Cases</h1>
      <p className="lede">
        Sanction publication resolutions observable in the current CNMV
        register snapshot, each linked to its BOE publication.
      </p>
      <div className="filters">
        <select value={severity} onChange={(e) => set("severity", e.target.value)}>
          <option value="">severity: all</option>
          <option value="VERY_SERIOUS">muy grave</option>
          <option value="SERIOUS">grave</option>
        </select>
        <input
          placeholder="statute contains… (e.g. 4/2015)"
          value={statute}
          onChange={(e) => set("statute", e.target.value)}
        />
        <input
          placeholder="respondent contains…"
          value={respondent}
          onChange={(e) => set("respondent", e.target.value)}
        />
      </div>
      {err && <div className="notice">{err}</div>}
      {!rows && !err && <p className="faint">loading…</p>}
      {rows && (
        <>
          <p className="faint">{rows.length} cases</p>
          <table className="data">
            <thead>
              <tr>
                <th>BOE</th><th>Title</th><th style={{ textAlign: "right" }}>Infr.</th>
                <th style={{ textAlign: "right" }}>Sanc.</th>
                <th>Published</th><th>Firmness</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.case_id}>
                  <td className="mono">
                    <Link to={`/cases/${c.case_id}`}>{c.canonical_boe_id}</Link>
                  </td>
                  <td className="small" style={{ maxWidth: 460 }}>
                    {(c.title_raw ?? "").replace(/^Resolución de /, "").slice(0, 140)}
                    {(c.title_raw ?? "").length > 140 ? "…" : ""}
                  </td>
                  <td className="num">{c.n_infringements}</td>
                  <td className="num">{c.n_sanctions}</td>
                  <td className="mono">{c.boe_publication_date ?? "—"}</td>
                  <td><FirmnessTag v={c.firmness_status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </>
  );
}
