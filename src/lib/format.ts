import type { Criterion } from '@/types'

const dateFormat = new Intl.DateTimeFormat('en-US', { dateStyle: 'long', timeZone: 'UTC' })

/** Formats an ISO date (yyyy-mm-dd) as "November 1, 2026". */
export function formatDate(iso: string | null): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : dateFormat.format(date)
}

/** Whole days from `earlier` to `later` (both ISO dates). */
export function daysBetween(later: string, earlier: string): number {
  return Math.floor((Date.parse(later) - Date.parse(earlier)) / 86_400_000)
}

export function formatMeasuredValue(valueType: Criterion['value_type'], value: number | null): string | null {
  if (value === null) return null
  switch (valueType) {
    case 'integer_pct':
      return `${value}%`
    case 'integer_days_or_null':
      return `${value} ${value === 1 ? 'day' : 'days'}`
    default:
      return String(value)
  }
}

export function languageName(code: string): string {
  try {
    return new Intl.DisplayNames(['en'], { type: 'language' }).of(code) ?? code
  } catch {
    return code
  }
}

export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${count} ${count === 1 ? singular : plural}`
}
