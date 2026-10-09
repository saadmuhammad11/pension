/** What may be attached, checked before a byte is sent (frontend review F8).
 *
 *  The server's limits (api/v2.py): 256 MB a file, 512 MB a request, 40 files. Checking here
 *  saves an officer on office Wi-Fi a twenty-minute upload that ends in a refusal. Types are
 *  judged by name: scanned PDFs and pictures, Word and Excel files (converted on the server),
 *  and zip archives. */
export const MAX_FILE_BYTES = 256 * 1024 * 1024
export const MAX_TOTAL_BYTES = 512 * 1024 * 1024
export const MAX_FILES = 40
export const ACCEPTED_EXTENSIONS = ['pdf', 'jpg', 'jpeg', 'png', 'tif', 'tiff', 'bmp', 'gif', 'webp', 'doc', 'docx', 'odt', 'rtf', 'txt', 'xls', 'xlsx', 'csv', 'zip']

const mb = (n: number) => `${Math.round(n / 1048576)} MB`

export type FileLike = { name: string; size: number }

export interface Checked<T extends FileLike> {
  accepted: T[]
  /** One line per file left out, in words the officer can act on. */
  refused: string[]
}

/** Add `incoming` to `have`: duplicates (same name and size) are skipped and said so; files over
 *  the limits, too many files, or an unknown type are refused with the reason. */
export function checkFiles<T extends FileLike>(have: T[], incoming: T[]): Checked<T> {
  const accepted = [...have]
  const refused: string[] = []
  let total = have.reduce((n, f) => n + f.size, 0)
  for (const f of incoming) {
    const ext = f.name.toLowerCase().split('.').pop() ?? ''
    if (accepted.some(x => x.name === f.name && x.size === f.size)) { refused.push(`${f.name}: already attached, skipped.`); continue }
    if (!ACCEPTED_EXTENSIONS.includes(ext)) { refused.push(`${f.name}: not a document type the office accepts (PDF, scanned image, Word, Excel or zip).`); continue }
    if (f.size > MAX_FILE_BYTES) { refused.push(`${f.name}: ${mb(f.size)} is over the ${mb(MAX_FILE_BYTES)} limit for one file.`); continue }
    if (accepted.length >= MAX_FILES) { refused.push(`${f.name}: at most ${MAX_FILES} files in one filing.`); continue }
    if (total + f.size > MAX_TOTAL_BYTES) { refused.push(`${f.name}: the filing would exceed ${mb(MAX_TOTAL_BYTES)} in all.`); continue }
    accepted.push(f); total += f.size
  }
  return { accepted, refused }
}

/** "12.4 MB of 30.1 MB sent" for the progress line. */
export function progressWords(sent: number, total: number): string {
  const f = (n: number) => `${(n / 1048576).toFixed(1)} MB`
  return `${f(sent)} of ${f(total)} sent`
}
