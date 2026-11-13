import { CircleMarker, MapContainer, Popup, TileLayer } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import type { FacilityRow } from '@/lib/facility-rows'

export function FacilityMap({ rows }: { rows: FacilityRow[] }) {
  const locations = rows.flatMap((row) =>
    row.coordinates ? [{ row, coordinates: row.coordinates }] : [],
  )

  return (
    <div className="space-y-2">
      <MapContainer
        aria-label="Map of New York hospitals, with markers colored by grade"
        bounds={[[40.45, -79.8], [45.05, -71.8]]}
        boundsOptions={{ padding: [12, 12] }}
        scrollWheelZoom={false}
        className="relative z-0 isolate h-36 w-full rounded-md"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {locations.map(({ row, coordinates }) => (
          <CircleMarker
            key={row.pfi}
            center={coordinates}
            radius={8}
            pathOptions={{
              color: 'var(--background)',
              weight: 2,
              fillColor: `var(--grade-${row.grade.grade.toLowerCase()})`,
              fillOpacity: 1,
            }}
          >
            <Popup>
              <span className="font-medium">{row.name}</span>
              <br />
              Grade {row.grade.grade}
            </Popup>
          </CircleMarker>
        ))}
      </MapContainer>
    </div>
  )
}
