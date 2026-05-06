import { Outlet, NavLink } from "react-router-dom";

const NAV = [
  { to: "/plant", label: "Plant" },
  { to: "/alerts", label: "Alerts" },
  { to: "/work-orders", label: "Work Orders" },
  { to: "/sustainability", label: "Sustainability" },
];

export default function App() {
  return (
    <div className="layout">
      <header className="header">
        <div className="brand">FactoryMind</div>
        <div className="plant-tag">PLANT-001 · Chennai Aerospace · Ti-6Al-4V</div>
      </header>
      <nav className="nav">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
