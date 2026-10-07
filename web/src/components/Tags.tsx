export function SeverityTag({ v }: { v: string }) {
  const cls = v === "VERY_SERIOUS" ? "vs" : v === "SERIOUS" ? "s" : "";
  const label =
    v === "VERY_SERIOUS" ? "muy grave" : v === "SERIOUS" ? "grave" : v === "MINOR" ? "leve" : v;
  return <span className={`tag ${cls}`}>{label}</span>;
}

export function SanctionTag({ v }: { v: string }) {
  const labels: Record<string, string> = {
    MONETARY_FINE: "multa",
    DISQUALIFICATION: "inhabilitación",
    DISGORGEMENT: "restitución",
    PUBLIC_REPRIMAND: "amonestación",
    SUSPENSION: "suspensión",
    UNKNOWN: "?",
  };
  const cls = v === "MONETARY_FINE" ? "fine" : "nm";
  return <span className={`tag ${cls}`}>{labels[v] ?? v}</span>;
}

export function RuleTag({ v }: { v: string }) {
  const labels: Record<string, string> = {
    VALID_FOR_CONDUCT: "rule valid for conduct",
    UNRESOLVED_RULE_VERSION: "rule version unresolved",
    NO_RULE_DEFINED: "no rule defined",
    AMBIGUOUS_VERSION: "ambiguous version",
  };
  const cls = v === "VALID_FOR_CONDUCT" ? "ok" : "dim";
  return <span className={`tag ${cls}`}>{labels[v] ?? v}</span>;
}

export function FirmnessTag({ v }: { v?: string | null }) {
  if (!v) return <span className="tag dim">—</span>;
  const labels: Record<string, string> = {
    FIRM_STATED: "firm (stated)",
    RENUNCIATION_OBSERVED: "firm by renunciation",
    APPEAL_POSSIBLE: "appeal possible",
    APPEAL_OBSERVED: "appeal observed",
    JUDGMENT_OBSERVED: "judgment observed",
    UNKNOWN: "unobserved",
  };
  const cls = v === "JUDGMENT_OBSERVED" || v === "APPEAL_OBSERVED" ? "vs" : v === "UNKNOWN" ? "dim" : "fine";
  return <span className={`tag ${cls}`}>{labels[v] ?? v}</span>;
}
