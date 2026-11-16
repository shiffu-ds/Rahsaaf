// How much a parked vehicle is holding up traffic. The word carries the
// meaning; the colour only reinforces it.
export default function ImpactBadge({ impact, long = false }) {
  if (!impact) return null;
  const kind = { High: "high", Medium: "medium", Low: "low" }[impact.level] || "low";
  return (
    <span className={`impact ${kind}`} title="How much this vehicle is holding up traffic">
      <span className="impact-mark" aria-hidden="true" />
      {long ? `${impact.level} traffic impact` : `${impact.level} impact`}
    </span>
  );
}
