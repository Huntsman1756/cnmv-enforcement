export default function Bars({
  rows,
  label,
}: {
  rows: { label: string; value: number; hint?: string }[];
  label?: string;
}) {
  const max = Math.max(...rows.map((r) => r.value), 1);
  return (
    <div className="bars">
      {label && <h3>{label}</h3>}
      {rows.map((r) => (
        <div className="row" key={r.label}>
          <div className="lbl">{r.label}</div>
          <div
            className="bar"
            style={{ width: `${Math.max((r.value / max) * 100, 1)}%` }}
          />
          <div className="val">
            {r.value.toLocaleString("es-ES")}
            {r.hint ? ` · ${r.hint}` : ""}
          </div>
        </div>
      ))}
    </div>
  );
}
