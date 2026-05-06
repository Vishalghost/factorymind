/**
 * Sustainability KPIs page.
 *
 * Live KPI feed requires an AppSync resolver on FactoryMind_SustainabilityKPIs.
 * Until that's wired, this page renders representative reference numbers from
 * the constants (carbon factor, energy cost) and a placeholder summary.
 */
export function Sustainability() {
  return (
    <>
      <h1>Sustainability</h1>
      <div className="panel">
        <h2>Plant KPIs (yesterday)</h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
          <Kpi label="Energy Efficiency" value="0.87" suffix="" tone="green" />
          <Kpi label="Carbon Footprint" value="1,420" suffix=" kg CO₂" tone="" />
          <Kpi label="Waste Index" value="0.12" suffix="" tone="green" />
          <Kpi label="Overall Score" value="84" suffix=" / 100" tone="green" />
        </div>
      </div>

      <div className="panel">
        <h2>Reference factors</h2>
        <table>
          <tbody>
            <tr><td>Carbon conversion</td><td><strong>0.82</strong> kg CO₂ / kWh (India grid)</td></tr>
            <tr><td>Energy cost</td><td><strong>₹7.50</strong> / kWh</td></tr>
            <tr><td>Recommendation source</td><td>Bedrock Claude 3.5 + Knowledge Bases</td></tr>
          </tbody>
        </table>
      </div>
    </>
  );
}

function Kpi({ label, value, suffix, tone }: { label: string; value: string; suffix: string; tone: string }) {
  return (
    <div style={{ background: "var(--panel-2)", padding: 16, borderRadius: 6 }}>
      <div style={{ fontSize: 12, color: "var(--muted)" }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 600, color: tone === "green" ? "var(--green)" : "var(--text)" }}>
        {value}<span style={{ fontSize: 14, color: "var(--muted)" }}>{suffix}</span>
      </div>
    </div>
  );
}
