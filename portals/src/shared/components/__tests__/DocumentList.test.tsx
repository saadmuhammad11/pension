/** F15: Replace is a real button; F12: a failed open is said, not swallowed. */
import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('../../portal', () => ({ portal: () => ({ slug: 'ag' }) }))
vi.mock('../../api/client', () => ({ openProtected: vi.fn(() => Promise.reject(new Error('The connection is slow or the server is busy.'))) }))

import { DocumentList } from '../DocumentList'

const doc = { id: 'd1', submission_no: 1, seq: 1, filename: 'frc.pdf', sha256: 'x', bytes: 2048, uploaded_by: 'u', uploaded_at: '2026-10-09T11:07:29' }

describe('DocumentList', () => {
  it('offers Replace as a keyboard-reachable button named for the paper', () => {
    render(<DocumentList caseId="c1" documents={[doc]} currentSubmission={1} onReplace={vi.fn()} />)
    const b = screen.getByRole('button', { name: 'Replace frc.pdf' })
    expect(b.tagName).toBe('BUTTON')
    expect(b).not.toHaveAttribute('tabindex', '-1')
  })
  it('says when a document could not be opened', async () => {
    render(<DocumentList caseId="c1" documents={[doc]} currentSubmission={1} />)
    fireEvent.click(screen.getByText('frc.pdf'))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Could not open the document. frc.pdf: The connection is slow'))
  })
  it('writes the upload moment the office way', () => {
    render(<DocumentList caseId="c1" documents={[doc]} currentSubmission={1} />)
    expect(screen.getByText('09 Oct 2026, 11:07')).toBeInTheDocument()
  })
})
