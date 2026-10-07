export interface CaseRow {
  case_id: string;
  canonical_boe_id: string;
  title_raw: string | null;
  sanctioning_resolution_date: string | null;
  publication_resolution_date: string | null;
  register_entry_date: string | null;
  boe_publication_date: string | null;
  administrative_finality_observed: boolean | null;
  judicial_review_mentioned: boolean | null;
  administrative_appeal_observed: boolean | null;
  n_infringements: number;
  n_sanctions: number;
  n_respondents: number;
  firmness_status?: string | null;
}

export interface Infringement {
  infringement_id: string;
  ordinal: number;
  severity: string;
  statute_normalized: string | null;
  article_normalized: string | null;
  conduct_raw: string | null;
  conduct_start_date: string | null;
  conduct_end_date: string | null;
  conduct_code: string;
  rule_version_id: string | null;
  rule_resolution_status: string;
  statute_raw?: string;
  article_raw?: string;
}

export interface Sanction {
  sanction_id: string;
  respondent_id: string;
  respondent_name?: string;
  ordinal: number;
  sanction_type: string;
  severity: string;
  amount: number | null;
  currency: string | null;
  amount_raw: string | null;
  duration_raw: string | null;
}

export interface Respondent {
  respondent_id: string;
  normalized_name: string | null;
  raw_display_name: string;
  respondent_type: string;
  role_raw: string | null;
  case_role?: string | null;
  source_anonymized: boolean;
  sanctions?: number;
  total_amount?: number | null;
  cases?: number;
}

export interface CaseDetail extends CaseRow {
  infringements: Infringement[];
  sanctions: Sanction[];
  respondents: Respondent[];
  evidence: {
    fact_type: string;
    entity_id: string;
    field_name: string;
    locator: string;
    excerpt: string;
    proof_level?: string | null;
    artifact_sha256?: string | null;
    representation?: string | null;
  }[];
  appeal_observation_status?: string | null;
  coverage_basis_id?: string | null;
  history_mode?: string | null;
  status_notes: { kind: string; page: number; verbatim: string }[];
  events: {
    event_type: string;
    event_date: string | null;
    source_document_id: string;
  }[];
}

export interface Stats {
  cases: number;
  infringements: number;
  sanctions: number;
  respondents: number;
  total_fine_eur: number;
  by_severity: { severity: string; n: number }[];
  by_sanction_type: { sanction_type: string; n: number; total: number | null }[];
  by_statute: { statute_normalized: string; n: number }[];
}

export interface CoverageDoc {
  scope_statement: string;
  counts?: {
    cases: number;
    infringements: number;
    sanctions: number;
    respondents: number;
  };
  sources?: {
    source: string;
    role: string;
    observed_from: string | null;
    observed_to: string | null;
    count: number;
  }[];
  boe_date_range?: { from: string; to: string };
  known_gaps?: string[];
  limitations?: string[];
  non_claims?: string[];
  unresolved_or_ambiguous?: string[];
}

const base = "/api";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${base}${path}`);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
}

export interface Meta {
  dataset_release: string | null;
  corpus_logical_sha256: string | null;
  dataset_schema_version?: number;
  code_commit?: string;
  api_version: string;
}

export const api = {
  metadata: () => get<Meta>("/metadata"),
  stats: () => get<Stats>("/stats"),
  coverage: () => get<CoverageDoc>("/coverage"),
  cases: (q: {
    severity?: string;
    statute?: string;
    respondent?: string;
    limit?: number;
    offset?: number;
  }) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(q))
      if (v !== undefined && v !== "") p.set(k, String(v));
    return get<{ cases: CaseRow[]; coverage_note: string }>(
      `/cases?${p}`
    );
  },
  case: (id: string) => get<CaseDetail>(`/cases/${id}`),
  respondents: (q?: string) =>
    get<{ respondents: Respondent[] }>(
      `/respondents${q ? `?q=${encodeURIComponent(q)}` : ""}`
    ),
  laws: () =>
    get<{
      statutes: { statute: string; infringements: number; cases: number }[];
    }>("/laws"),
  article: (statute: string, article: string) =>
    get<{ infringements: Infringement[] }>(
      `/laws/${encodeURIComponent(statute)}/articles/${encodeURIComponent(article)}`
    ),
};

export function eur(n: number | null | undefined): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: "EUR",
    maximumFractionDigits: 0,
  }).format(n);
}
