import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Cameras drawn as circles on a street map; a bigger circle means more
// violations there. The same figures are in the table beside it, so nothing
// depends on the map tiles loading.
export default function HotspotMap({ spots }) {
  const element = useRef(null);
  const placed = spots.filter((s) => s.latitude != null && s.longitude != null);

  useEffect(() => {
    if (!element.current || placed.length === 0) return undefined;
    const map = L.map(element.current, { scrollWheelZoom: false });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map);

    const most = Math.max(1, ...placed.map((s) => s.violations));
    const points = placed.map((spot) => {
      const point = [spot.latitude, spot.longitude];
      // Area, not radius, follows the count, so twice the violations looks twice as big.
      const radius = 8 + 22 * Math.sqrt(spot.violations / most);
      const circle = L.circleMarker(point, {
        radius,
        color: "#184f95",
        weight: 2,
        fillColor: "#2a78d6",
        fillOpacity: 0.45,
      }).addTo(map);
      const label = document.createElement("div");
      const name = document.createElement("strong");
      name.textContent = spot.camera_name;
      label.append(name, document.createElement("br"), `${spot.violations} violation(s)`);
      circle.bindPopup(label);
      circle.bindTooltip(`${spot.camera_name}: ${spot.violations}`);
      return point;
    });

    if (points.length === 1) map.setView(points[0], 15);
    else map.fitBounds(points, { padding: [40, 40], maxZoom: 16 });
    return () => map.remove();
    // Rebuild only when the figures change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(placed)]);

  if (placed.length === 0) {
    return (
      <div className="map empty muted">
        No camera has a position yet. Start the camera worker with --lat and --lon to see it here.
      </div>
    );
  }
  return <div className="map" ref={element} role="application" aria-label="Map of cameras sized by number of violations" />;
}
