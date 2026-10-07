import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../lib/api";

type Statute = { statute: string; infringements: number; cases: number };

export default function Laws() {
  const [rows, setRows] = useState<Statute[] | null>(null);
  useEffect(() => {
    api.laws().then((r) => setRows(r.statutes));
  }, []);
  return (
    <>
      <h1>Legal basis</h1>
      <p className="lede">
        Statutes as typified in the publications. Historical statutes are
        normalized; the applicable rule version is resolved per infringement
        and flagged when unresolved.
      </p>
      {!rows && <p className="faint">loading…</p>}
      {rows && (
        <table className="data">
          <thead>
            <tr><th>Statute (normalized)</th><th style={{ textAlign: "right" }}>Infringements</th><th style={{ textAlign: "right" }}>Cases</th></tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.statute}>
                <td className="mono">{s.statute}</td>
                <td className="num">{s.infringements}</td>
                <td className="num">{s.cases}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="small faint">
        Tip: use <Link to="/cases?statute=4%2F2015">Cases</Link> with the
        statute filter to see articles in context.
      </p>
    </>
  );
}
