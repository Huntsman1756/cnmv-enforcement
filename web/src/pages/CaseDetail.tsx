import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, eur, type CaseDetail as CD } from "../lib/api";
import { RuleTag, SanctionTag, SeverityTag } from "../components/Tags";

export default function CaseDetail() {
  const { id } = useParams<{ id: string }>();
  const [c, setC] = useState<CD | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (id) api.case(id).then(setC).catch((e) => setErr(String(e)));
  }, [id]);
  if (err) return <div className="notice">{err}</div>;
  if (!c) return <p className="faint">loading…</p>;

  const total = c.sanctions
    .filter((s) => s.sanction_type === "MONETARY_FINE" && s.amount)
    .reduce((a, s) => a + (s.amount ?? 0), 0);

  return (
    <>
      <p className="small"><Link to="/cases">← cases</Link></p>
      <h1 className="mono">{c.canonical_boe_id}</h1>
      <p className="lede">{c.title_raw}</p>
      <div className="panel">
        <div className="fact"><div className="k">sanctioning resolution</div><div>{c.sanctioning_resolution_date ?? "—"}</div></div>
        <div className="fact"><div className="k">publication resolution</div><div>{c.publication_resolution_date ?? "—"}</div></div>
        <div className="fact"><div className="k">BOE publication</div><div>{c.boe_publication_date ?? "—"}</div></div>
        <div className="fact"><div className="k">register entry</div><div>{c.register_entry_date ?? "—"}</div></div>
        <div className="fact"><div className="k">administrative finality (observed)</div><div>{c.administrative_finality_observed ? "stated in publication" : "not stated"}</div></div>
        <div className="fact"><div className="k">judicial review mentioned</div><div>{c.judicial_review_mentioned ? "yes" : "no"}</div></div>
        <div className="fact"><div className="k">total fines</div><div className="mono">{eur(total)}</div></div>
      </div>

      <h2>Respondents ({c.respondents.length})</h2>
      <table className="data">
        <thead><tr><th>Name</th><th>Type</th><th>Role (verbatim)</th></tr></thead>
        <tbody>
          {c.respondents.map((r) => (
            <tr key={r.respondent_id}>
              <td>
                <Link to={`/respondents?q=${encodeURIComponent(r.normalized_name ?? "")}`}>
                  {r.normalized_name ?? r.raw_display_name}
                </Link>
                {r.source_anonymized && <span className="tag dim" style={{ marginLeft: 8 }}>source-anonymized</span>}
              </td>
              <td className="small">{r.respondent_type}</td>
              <td className="small faint">{r.role_raw ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Infringements ({c.infringements.length})</h2>
      {c.infringements.map((i) => (
        <div className="infr-box" key={i.infringement_id}>
          <div className="head">
            <SeverityTag v={i.severity} />
            <span className="mono">
              art. {i.article_normalized ?? "?"} — {i.statute_normalized ?? "?"}
            </span>
            <RuleTag v={i.rule_resolution_status} />
          </div>
          <div className="body">
            {i.conduct_raw && <div className="excerpt">{i.conduct_raw}</div>}
            <div className="ruleline">
              {i.rule_version_id ? `rule: ${i.rule_version_id}` : "no resolved rule version"}
              {i.conduct_start_date
                ? ` · conduct ${i.conduct_start_date}${i.conduct_end_date && i.conduct_end_date !== i.conduct_start_date ? `→${i.conduct_end_date}` : ""}`
                : " · conduct dates unextracted"}
              {` · raw: ${i.article_raw ?? "—"}`}
            </div>
          </div>
        </div>
      ))}

      <h2>Sanctions ({c.sanctions.length})</h2>
      <table className="data">
        <thead>
          <tr><th>#</th><th>Respondent</th><th>Type</th><th style={{ textAlign: "right" }}>Amount</th><th>Duration</th></tr>
        </thead>
        <tbody>
          {c.sanctions.map((s) => (
            <tr key={s.sanction_id}>
              <td className="num">{s.ordinal}</td>
              <td className="small">{s.respondent_name ?? s.respondent_id}</td>
              <td><SanctionTag v={s.sanction_type} /></td>
              <td className="num">{eur(s.amount)}</td>
              <td className="small faint">{s.duration_raw ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {c.status_notes.length > 0 && (
        <>
          <h2>CNMV-document status notes</h2>
          {c.status_notes.map((n, i) => (
            <div className="panel" key={i}>
              <span className="tag">{n.kind}</span>{" "}
              <span className="faint small">page {n.page}</span>
              <div className="excerpt">{n.verbatim}</div>
            </div>
          ))}
        </>
      )}

      <h2>Events</h2>
      <div className="tl">
        {c.events.map((e, i) => (
          <div className="evt" key={i}>
            <div className="d">{e.event_date ?? "—"}</div>
            <div className="t">{e.event_type}</div>
            <div className="s">{e.source_document_id}</div>
          </div>
        ))}
      </div>

      <h2>Evidence ({c.evidence.length} records)</h2>
      <details className="ev">
        <summary>show all evidence records</summary>
        {c.evidence.map((e, i) => (
          <div className="excerpt" key={i}>
            <strong>[{e.fact_type}]</strong> {e.entity_id}
            <br />
            <span className="faint">{e.locator}</span>
            <br />
            {e.excerpt}
          </div>
        ))}
      </details>
      <div className="notice" style={{ marginTop: 18 }}>
        <strong>Reading note:</strong> a BOE publication resolution is not
        necessarily the complete underlying sanctioning decision; publication
        dates are not offence dates; and no observed appeal does not mean no
        appeal exists.
      </div>
    </>
  );
}
