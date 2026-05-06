export function Logo({ className = "" }: { className?: string }) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <div className="relative h-8 w-8 rounded-lg bg-gradient-to-br from-primary to-chart-5 shadow-md">
        <div className="absolute inset-1.5 rounded-md border-2 border-primary-foreground/80" />
        <div className="absolute left-1/2 top-1/2 h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary-foreground" />
      </div>
      <span className="font-display text-lg font-bold tracking-tight">FactoryMind</span>
    </div>
  );
}
