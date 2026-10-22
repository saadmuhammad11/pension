/** F14: the override names the statuses in words and says the change is audited. */
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { ActionPanel } from '../ActionPanel'

describe('ActionPanel override', () => {
  it('shows status labels, not codes, and "Setting from X to Y. This is audited."', () => {
    render(<ActionPanel actions={['OVERRIDE']} hasIssues={false} busy={false} onAct={vi.fn(async () => {})} status="UNDER_REVIEW" />)
    fireEvent.click(screen.getByRole('button', { name: 'Override decision' }))
    const select = screen.getByLabelText('Set the case to') as HTMLSelectElement
    expect(Array.from(select.options).map(o => o.text)).toContain('Returned for correction')
    expect(Array.from(select.options).map(o => o.text)).not.toContain('RETURNED')
    expect(screen.getByText(/Setting from Under review at AG Office to Returned for correction\. This is audited\./)).toBeInTheDocument()
    fireEvent.change(select, { target: { value: 'APPROVED' } })
    expect(screen.getByText(/to Approved\. This is audited\./)).toBeInTheDocument()
  })
})
