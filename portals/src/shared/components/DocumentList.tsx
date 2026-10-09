/** The papers on the case, by round of submission, each downloadable. */
import { useRef, useState } from 'react'
import { openProtected } from '../api/client'
import { documentUrl, type CaseDocument } from '../api/cases'
import { fmtDateTime } from '../fmt'

const kb = (n: number) => n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1048576).toFixed(1)} MB`

export function DocumentList({ caseId, documents, currentSubmission, onReplace, busy = false }:
  { caseId: string; documents: CaseDocument[]; currentSubmission: number
    /** Offered while the case is on the department's side: file a corrected paper in its place. */
    onReplace?: (doc: CaseDocument, file: File) => void
    busy?: boolean }) {
  // A failed open used to close the blank tab and say nothing (F12); now it says what happened.
  const [openError, setOpenError] = useState<string | null>(null)
  // One hidden file input for the whole list; "Replace" is a real button, reachable from the
  // keyboard (F15), and remembers which paper it is replacing.
  const picker = useRef<HTMLInputElement>(null)
  const replacing = useRef<CaseDocument | null>(null)
  if (!documents.length) return <div className="empty">No documents on this case yet.</div>
  const rounds = [...new Set(documents.map(d => d.submission_no))].sort((a, b) => b - a)
  const open = (d: CaseDocument) => {
    setOpenError(null)
    openProtected(documentUrl(caseId, d.id), d.filename).catch(e => setOpenError(`${d.filename}: ${e instanceof Error ? e.message : String(e)}`))
  }
  return (
    <div className="stack">
      {onReplace && (
        <input ref={picker} type="file" hidden disabled={busy} accept=".pdf,.jpg,.jpeg,.png,.tif,.tiff,.zip" aria-hidden="true" tabIndex={-1}
               onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; const d = replacing.current; replacing.current = null; if (f && d) onReplace(d, f) }} />
      )}
      {openError && <div className="banner bad" role="alert"><span className="mark">!</span><div className="sub">Could not open the document. {openError}</div></div>}
      {rounds.map(r => (
        <div key={r}>
          {rounds.length > 1 && (
            <div className="label" style={{ margin: '6px 0' }}>
              Submission {r}{r === currentSubmission ? ' (current)' : ''}
            </div>
          )}
          <table>
            <tbody>
              {documents.filter(d => d.submission_no === r).map(d => (
                <tr key={d.id}>
                  <td className="mono muted" style={{ width: 40 }}>{d.seq}</td>
                  <td style={d.superseded_in_submission ? { opacity: .55 } : undefined}>
                    <a href={documentUrl(caseId, d.id)} rel="noreferrer" className="doc-link"
                       style={d.superseded_in_submission ? { textDecoration: 'line-through' } : undefined}
                       onClick={e => { e.preventDefault(); open(d) }}>
                      {d.filename}
                    </a>
                    {d.superseded_in_submission ? <span className="pill neutral" style={{ marginLeft: 8 }}>replaced in submission {d.superseded_in_submission}</span> : null}
                    {d.replaces_document_id ? <span className="pill info" style={{ marginLeft: 8 }}>replacement for {documents.find(x => x.id === d.replaces_document_id)?.filename ?? 'an earlier paper'}</span> : null}
                  </td>
                  {onReplace && (
                    <td style={{ width: 96 }}>
                      {!d.superseded_in_submission && (
                        <button type="button" disabled={busy} aria-label={`Replace ${d.filename}`}
                                style={{ fontSize: 'var(--t-small)', padding: '4px 10px', minHeight: 0 }}
                                onClick={() => { replacing.current = d; picker.current?.click() }}>
                          Replace
                        </button>
                      )}
                    </td>
                  )}
                  <td className="muted num" style={{ width: 90 }}>{kb(d.bytes)}</td>
                  <td className="muted" style={{ width: 170, fontSize: 'var(--t-small)' }}>{fmtDateTime(d.uploaded_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}
