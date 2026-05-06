import { jsPDF } from "jspdf";
import type { Machine } from "./mockData";

export function generateFaultReport(machines: Machine[]) {
  const doc = new jsPDF({ unit: "pt", format: "a4" });
  const W = doc.internal.pageSize.getWidth();
  let y = 50;

  // Header band
  doc.setFillColor(79, 70, 229);
  doc.rect(0, 0, W, 80, "F");
  doc.setTextColor(255, 255, 255);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(22);
  doc.text("FactoryMind — Fault & Health Report", 40, 45);
  doc.setFontSize(10);
  doc.setFont("helvetica", "normal");
  doc.text(`Generated ${new Date().toLocaleString()}  ·  Confidential`, 40, 65);
  y = 110;

  doc.setTextColor(20, 20, 30);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(13);
  doc.text("Executive Summary", 40, y); y += 18;
  doc.setFont("helvetica", "normal");
  doc.setFontSize(10);
  const critical = machines.filter((m) => m.status === "critical");
  const warning = machines.filter((m) => m.status === "warning");
  const avgHealth = Math.round(machines.reduce((s, m) => s + m.health, 0) / machines.length);
  const lines = [
    `Assets monitored: ${machines.length}`,
    `Average fleet health: ${avgHealth}%`,
    `Critical faults: ${critical.length}   ·   Warnings: ${warning.length}`,
    `Estimated savings if acted upon: Rs. ${(critical.length * 12 + warning.length * 4)} Lakhs`,
  ];
  lines.forEach((l) => { doc.text(l, 40, y); y += 14; });
  y += 10;

  // Faults section
  const faulty = [...critical, ...warning];
  doc.setFont("helvetica", "bold");
  doc.setFontSize(13);
  doc.text("Detected Faults & Locations", 40, y); y += 8;
  doc.setDrawColor(79, 70, 229);
  doc.line(40, y, W - 40, y); y += 16;

  faulty.forEach((m, i) => {
    if (y > 740) { doc.addPage(); y = 50; }
    const isCrit = m.status === "critical";
    doc.setFillColor(isCrit ? 254 : 255, isCrit ? 226 : 247, isCrit ? 226 : 214);
    doc.roundedRect(40, y - 2, W - 80, 86, 6, 6, "F");
    doc.setTextColor(isCrit ? 153 : 146, isCrit ? 27 : 64, isCrit ? 27 : 14);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(11);
    doc.text(`${i + 1}. ${m.name}  [${m.id}]  —  ${m.status.toUpperCase()}`, 50, y + 14);
    doc.setFont("helvetica", "normal");
    doc.setFontSize(9);
    doc.setTextColor(40, 40, 40);
    doc.text(`Location: ${m.line}  ·  Position (X,Y,Z): ${m.position.join(", ")}`, 50, y + 30);
    doc.text(`Health: ${m.health}%   Temp: ${m.temp.toFixed(1)}°C   Vibration: ${m.vibration.toFixed(2)} mm/s   Load: ${m.load.toFixed(0)}%`, 50, y + 44);
    const fault = inferFault(m);
    doc.text(`Detected fault: ${fault.label}`, 50, y + 58);
    doc.text(`Recommended action: ${fault.action}`, 50, y + 72);
    if (m.predictedFailureHours) {
      doc.setTextColor(153, 27, 27);
      doc.setFont("helvetica", "bold");
      doc.text(`⚠ Predicted failure in ~${m.predictedFailureHours}h`, W - 200, y + 14);
    }
    y += 96;
  });

  // Healthy assets table
  if (y > 680) { doc.addPage(); y = 50; }
  y += 10;
  doc.setTextColor(20, 20, 30);
  doc.setFont("helvetica", "bold");
  doc.setFontSize(13);
  doc.text("All Assets Snapshot", 40, y); y += 16;
  doc.setFontSize(9);
  doc.setFont("helvetica", "bold");
  ["ID", "Name", "Line", "Status", "Health", "Temp", "Vib"].forEach((h, i) => {
    doc.text(h, 40 + i * 75, y);
  });
  y += 6;
  doc.setDrawColor(200);
  doc.line(40, y, W - 40, y); y += 12;
  doc.setFont("helvetica", "normal");
  machines.forEach((m) => {
    if (y > 780) { doc.addPage(); y = 50; }
    [m.id, m.name.slice(0, 14), m.line, m.status, `${m.health}%`, `${m.temp.toFixed(0)}°`, m.vibration.toFixed(2)].forEach((c, i) => {
      doc.text(String(c), 40 + i * 75, y);
    });
    y += 14;
  });

  doc.save(`FactoryMind-Report-${Date.now()}.pdf`);
}

function inferFault(m: Machine) {
  if (m.temp > 95) return { label: "Thermal overload — coolant flow degraded", action: "Inspect coolant lines and replace filter; throttle load to 70%." };
  if (m.vibration > 4) return { label: "Excessive vibration — bearing wear suspected", action: "Schedule spindle bearing replacement within 24h." };
  if (m.health < 50) return { label: "Composite health critical — multi-sensor anomaly", action: "Stop machine, run full diagnostic, replace seals & bearings." };
  if (m.health < 75) return { label: "Early-stage degradation pattern detected", action: "Schedule preventive maintenance within 48h." };
  return { label: "Operating within nominal envelope", action: "Continue routine monitoring." };
}
