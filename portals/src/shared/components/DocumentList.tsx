/** The papers on the case, by round of submission, each downloadable. */
import { openProtected } from '../api/client'
import { documentUrl, type CaseDocument } from '../api/cases'

const kb = (n: number) => n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} KB` : `${(n / 1048576).toFixed(1)} MB`

export function DocumentList({ caseId, documents, currentSubmission, onReplace, busy = false }:
  { caseId: string; documents: CaseDocument[]; currentSubmission: number
    /** Offered while the case is on the department's side: file a corrected paper in its place. */
    onReplace?: (doc: CaseDocument, file: File) => void
    busy?: boolean }) {
  if (!documents.length) return <div className="empty">No documents on this case yet.</div>
  const rounds = [...new Set(documents.map(d => d.submission_no))].sort((a, b) => b - a)
  return (
    <div className="stack">
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
                    <a href={documentUrl(caseId, d.id)} rel="noreferrer"
                       style={d.superseded_in_submission ? { textDecoration: 'line-through' } : undefined}
                       onClick={e => { e.preventDefault(); openProtected(documentUrl(caseId, d.id), d.filename).catch(() => { /* the session handler shows the sign-in page on 401 */ }) }}>
                      {d.filename}
                    </a>
                    {d.superseded_in_submission ? <span className="pill neutral" style={{ marginLeft: 8 }}>replaced in submission {d.superseded_in_submission}</span> : null}
                    {d.replaces_document_id ? <span className="pill info" style={{ marginLeft: 8 }}>replacement for {documents.find(x => x.id === d.replaces_document_id)?.filename ?? 'an earlier paper'}</span> : null}
                  </td>
                  {onReplace && (
                    <td style={{ width: 96 }}>
                      {!d.superseded_in_submission && (
                        <label className="btn" style={{ cursor: busy ? 'default' : 'pointer', fontSize: 'var(--t-small)', padding: '4px 10px', border: '1px solid var(--line)', borderRadius: 8 }}>
                          Replace
                          <input type="file" hidden disabled={busy} accept=".pdf,.jpg,.jpeg,.png,.tif,.tiff,.zip"
                                 onChange={e => { const f = e.target.files?.[0]; e.target.value = ''; if (f) onReplace(d, f) }} />
                        </label>
                      )}
                    </td>
                  )}
                  <td className="muted num" style={{ width: 90 }}>{kb(d.bytes)}</td>
                  <td className="muted" style={{ width: 170, fontSize: 'var(--t-small)' }}>{d.uploaded_at.replace('T', ' ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  )
}
