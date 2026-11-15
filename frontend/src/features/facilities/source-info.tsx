import { ExternalLink } from 'lucide-react'
import { DOC_TYPE_LABELS } from '@/content/criteria-copy'
import { formatDate } from '@/lib/format'
import type { Assessment, Document as FaDocument } from '@/types'

interface SourceInfoProps {
  assessment: Assessment | null
  document: FaDocument | undefined
}

/** Never blank and never invented: shows exactly what is recorded, or "No source recorded". */
export function SourceInfo({ assessment, document }: SourceInfoProps) {
  const quote = assessment?.evidence_quote ?? null
  if (!assessment || (!document && !quote)) {
    return <p className="text-xs text-muted-foreground">Source: No source recorded</p>
  }
  return (
    <div className="space-y-1 text-xs text-muted-foreground">
      <p>
        Source:{' '}
        {document ? (
          <>
            {document.url ? (
              <a href={document.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 rounded-sm text-primary underline underline-offset-4 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50">
                {DOC_TYPE_LABELS[document.doc_type]}
                <ExternalLink aria-hidden className="size-3" />
                <span className="sr-only">(opens in new tab)</span>
              </a>
            ) : (
              DOC_TYPE_LABELS[document.doc_type]
            )}
            {' · '}Retrieved {formatDate(document.retrieved_at)}
          </>
        ) : (
          'Document not identified'
        )}
      </p>
      {quote ? <blockquote className="border-l-2 pl-3 text-foreground italic">“{quote}”</blockquote> : <p>No quote recorded</p>}
    </div>
  )
}
