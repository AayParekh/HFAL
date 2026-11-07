import { Navigate, Route, Routes } from 'react-router-dom'
import { DemoBanner } from '@/components/demo-banner'
import { FacilitiesPage } from '@/features/facilities/facilities-page'

// Future routes (statewide map, recent updates) slot in here.
export function App() {
  return (
    <>
      <DemoBanner />
      <main>
        <Routes>
          <Route path="/" element={<FacilitiesPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </>
  )
}
