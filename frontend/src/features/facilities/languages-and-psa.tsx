import { Badge } from '@/components/ui/badge'
import { DOC_TYPE_LABELS } from '@/content/criteria-copy'
import { languageName } from '@/lib/format'
import type { FacilityPsa, Package, PackageLanguage } from '@/types'

function scopeLabel(docType: PackageLanguage['doc_type']): string {
  return docType === 'all' ? '' : ` (${DOC_TYPE_LABELS[docType].toLowerCase()} only)`
}

export function LanguagesAndPsa({ pkg, psa }: { pkg: Package; psa: FacilityPsa | null }) {
  const counties = psa?.counties_listed ?? []
  return (
    <dl className="space-y-3 text-sm">
      <div>
        <dt className="font-medium">Languages available</dt>
        <dd className="mt-1 flex flex-wrap gap-2">
          {pkg.languages.length === 0 ? (
            <span className="text-muted-foreground">Not recorded</span>
          ) : (
            pkg.languages.map((language) => (
              <Badge key={`${language.doc_type}-${language.language_code}`} variant="secondary">
                {languageName(language.language_code)}
                {scopeLabel(language.doc_type)}
              </Badge>
            ))
          )}
        </dd>
      </div>
      <div>
        <dt className="font-medium">Primary service area counties</dt>
        <dd className="mt-1">{counties.length > 0 ? counties.join(', ') : <span className="text-muted-foreground">Not listed</span>}</dd>
      </div>
    </dl>
  )
}
