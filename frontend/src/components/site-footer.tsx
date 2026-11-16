// The public repository: the pipeline, its documentation (README, docs/technical.md) and this front end.
export const REPOSITORY_URL = 'https://github.com/AayParekh/HFAL'

export function SiteFooter() {
  return (
    <footer className="mx-auto w-full max-w-6xl border-t border-border px-4 py-6 text-sm text-muted-foreground">
      <p>
        More info and source code:{' '}
        <a
          href={REPOSITORY_URL}
          target="_blank"
          rel="noopener noreferrer"
          className="font-medium text-foreground underline underline-offset-4 hover:no-underline"
        >
          github.com/AayParekh/HFAL
        </a>
      </p>
    </footer>
  )
}
