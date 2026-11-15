import { CircleMarker, MapContainer, Popup, TileLayer } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import type { FacilityRow } from '@/lib/facility-rows'
import type { UnassessedFacility } from '@/types'

const GRADES = ['A', 'B', 'C', 'D', 'F'] as const
// Hospitals the tool has not checked: gray, drawn under the graded markers.
const NOT_CHECKED_COLOR = 'var(--muted-foreground)'

export function FacilityMap({ rows, unassessed = [] }: { rows: FacilityRow[]; unassessed?: UnassessedFacility[] }) {
  const locations = rows.flatMap((row) =>
    row.coordinates ? [{ row, coordinates: row.coordinates }] : [],
  )
  const grayLocations = unassessed.flatMap((hospital) =>
    hospital.coordinates ? [{ hospital, coordinates: hospital.coordinates }] : [],
  )

  return (
    <div className="space-y-2">
      <MapContainer
        aria-label="Map of New York hospitals, with markers colored by grade and gray for hospitals not checked"
        bounds={[[40.45, -79.8], [45.05, -71.8]]}
        boundsOptions={{ padding: [12, 12] }}
        scrollWheelZoom={false}
        className="relative z-0 isolate h-[280px] w-full rounded-md"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {grayLocations.map(({ hospital, coordinates }) => (
          <CircleMarker
            key={`unassessed-${hospital.pfi}`}
            center={coordinates}
            radius={6}
            pathOptions={{
              color: 'var(--background)',
              weight: 1.5,
              fillColor: NOT_CHECKED_COLOR,
              fillOpacity: 0.85,
            }}
          >
            <Popup>
              <span className="font-medium">{hospital.name}</span>
              <br />
              Not checked by the tool
            </Popup>
          </CircleMarker>
        ))}
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
      <ul className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground" aria-label="Map legend">
        {GRADES.map((grade) => (
          <li key={grade} className="flex items-center gap-1">
            <span aria-hidden className="inline-block size-2.5 rounded-full" style={{ background: `var(--grade-${grade.toLowerCase()})` }} />
            {grade}
          </li>
        ))}
        <li className="flex items-center gap-1">
          <span aria-hidden className="inline-block size-2.5 rounded-full" style={{ background: NOT_CHECKED_COLOR }} />
          Not checked
        </li>
      </ul>
    </div>
  )
}
