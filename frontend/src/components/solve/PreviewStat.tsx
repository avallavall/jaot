/** Small stat card used in file-import preview screens. */
export function PreviewStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="p-3 bg-muted/20 border border-border rounded-md">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-sm font-semibold mt-0.5">{value}</p>
    </div>
  );
}
