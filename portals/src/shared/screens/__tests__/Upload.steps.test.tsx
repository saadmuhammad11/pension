/** A GP Fund claim is filed in the same four steps as a pension case (23 Oct 2026).
 *
 *  The kind of claim used to sit in the third card, below the papers, and started as Final
 *  payment -- so a claim could be attached and filed without the kind ever being looked at,
 *  and a refundable advance filed as a final payment is examined against the wrong checks.
 *  It is now step one for both products: the case type for a pension case, the kind of claim
 *  for a GP Fund one, mandatory, with nothing attachable before it is chosen.
 */
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Upload } from '../Upload'

vi.mock('../../portal', () => ({ portal: () => ({ slug: 'dept' }) }))
vi.mock('../../api/cases', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api/cases')>()),
  // The department's own DDO files for its own department, so neither list is fetched; a test
  // that let them through would be asserting against the network.
  fetchCaseTypes: () => Promise.resolve([]),
  departments: () => Promise.resolve([]),
  createCase: vi.fn(),
  fetchGpfClaimKinds: (gazetted: string) => Promise.resolve([
    {
      id: 'death', label: 'Final payment — death', documents: [
        { id: 'COVER', item: 'A2-i', requirement: 'Covering / forwarding letter', always: true },
        { id: 'DEATH-HEIRS', item: 'A2-iv', requirement: 'CNIC copies of all legal heirs', always: true },
        { id: 'DEATH-AFFIDAVIT', item: 'A2-vi', requirement: 'Original affidavit for lawful widow', always: false },
      ],
    },
    {
      id: 'missing_credits', label: 'Missing credits', documents: [
        { id: 'MC-PERIOD', item: 'A4-ii', requirement: 'Period of missing months', always: true },
        // The certificate that depends on what the department said about the subscriber.
        ...(gazetted === 'gazetted'
          ? [{ id: 'MC-AG-CERT', item: 'A4-iv', requirement: 'Manual deduction certificate by AG Office (gazetted period)', always: true }]
          : [{ id: 'MC-DDO-CERT', item: 'A4-iii', requirement: 'Manual deduction certificate by DDO, with bills and acquaintance roll (non-gazetted period)', always: true }]),
      ],
    },
    { id: 'refundable', label: 'Refundable advance', documents: [] },
  ]),
}))
vi.mock('../../auth/AuthProvider', () => ({
  useSession: () => ({ can: { pick_department: false, intake_choices: false }, user: { department_name: 'S&GAD' } }),
}))

afterEach(cleanup)

const draw = (product: 'PENSION' | 'GPF') =>
  render(<Upload product={product} onCreated={() => {}} onCancel={() => {}} />)

/** The numbered step headings, in the order they are drawn. */
const steps = () => screen.getAllByRole('heading', { level: 3 }).map(h => h.textContent ?? '')

/** The card a step heading belongs to. The heading carries its number in a span, so it is
 *  found by its own text rather than by an accessible name. */
const card = (heading: string) =>
  screen.getAllByRole('heading', { level: 3 })
    .find(h => h.textContent === heading)!.closest('.card') as HTMLElement

describe('both products are filed in the same four steps', () => {
  it('a GP Fund claim: the claim type, the papers, the subscriber, file it', () => {
    draw('GPF')
    expect(steps()).toEqual(['1Claim type', '2Attach the documents', '3Subscriber'])
    // The fourth step is the filing card, which carries its number beside the button.
    expect(screen.getByRole('button', { name: 'File claim and submit' })).toBeTruthy()
  })

  it('a pension case: the case type, the papers, the claimant, file it', () => {
    draw('PENSION')
    expect(steps()).toEqual(['1Case type', '2Attach the documents', '3Claimant'])
    expect(screen.getByRole('button', { name: 'File case and submit' })).toBeTruthy()
  })
})

describe('the kind of claim is chosen before anything is attached', () => {
  it('starts empty, so no kind is assumed', () => {
    draw('GPF')
    expect(screen.getByLabelText(/Kind of claim/)).toHaveProperty('value', '')
  })

  it('the file input is disabled and the drop zone says what to do first', () => {
    draw('GPF')
    expect(screen.getByLabelText('Select the documents')).toHaveProperty('disabled', true)
    expect(screen.getByText('Select the kind of claim first')).toBeTruthy()
  })

  it('choosing a kind opens the papers and explains what the kind is', () => {
    draw('GPF')
    fireEvent.change(screen.getByLabelText(/Kind of claim/), { target: { value: 'refundable' } })
    expect(screen.getByLabelText('Select the documents')).toHaveProperty('disabled', false)
    expect(screen.getByText(/recovered from the subscriber's pay in instalments/)).toBeTruthy()
  })

  it('filing is refused until the kind is chosen', () => {
    draw('GPF')
    expect(screen.getByRole('button', { name: 'File claim and submit' })).toHaveProperty('disabled', true)
    // Reaching for the papers first is the way an officer meets this, and it says which step.
    fireEvent.click(screen.getByText('Select the kind of claim first'))
    expect(screen.getByRole('alert').textContent).toBe('Select the kind of claim before attaching documents.')
  })

  it('the pension case says "case type" in the same places', () => {
    draw('PENSION')
    expect(screen.getByRole('button', { name: 'File case and submit' })).toHaveProperty('disabled', true)
    fireEvent.click(screen.getByText('Select the case type first'))
    expect(screen.getByRole('alert').textContent).toBe('Select the case type before attaching documents.')
  })
})

describe('choosing the kind shows what the office checks it for', () => {
  it('lists the papers, as a pension case type lists its documents', async () => {
    draw('GPF')
    fireEvent.change(screen.getByLabelText(/Kind of claim/), { target: { value: 'death' } })
    expect(await screen.findByText('Documents required for Final payment — death:')).toBeTruthy()
    const required = within(card('1Claim type')).getAllByRole('list')[0].textContent ?? ''
    expect(required).toContain('Covering / forwarding letter')
    expect(required).toContain('CNIC copies of all legal heirs')
  })

  it('a paper wanted only sometimes is listed apart, not among the rest', async () => {
    draw('GPF')
    fireEvent.change(screen.getByLabelText(/Kind of claim/), { target: { value: 'death' } })
    expect(await screen.findByText('And where it applies:')).toBeTruthy()
    const lists = within(card('1Claim type')).getAllByRole('list')
    // The ordered list is what every death claim needs; the affidavit is in the second list.
    expect(lists[0].textContent).not.toContain('affidavit')
    expect(lists[1].textContent).toContain('Original affidavit for lawful widow')
  })

  it('the list follows the subscriber, where the papers differ', async () => {
    draw('GPF')
    fireEvent.change(screen.getByLabelText(/Kind of claim/), { target: { value: 'missing_credits' } })
    expect(await screen.findByText(/certificate by DDO/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Subscriber'), { target: { value: 'gazetted' } })
    expect(await screen.findByText(/certificate by AG Office/)).toBeTruthy()
    expect(screen.queryByText(/certificate by DDO/)).toBeNull()
  })

  it('a kind the module lists no papers for says so rather than showing an empty list', async () => {
    draw('GPF')
    fireEvent.change(screen.getByLabelText(/Kind of claim/), { target: { value: 'refundable' } })
    expect(await screen.findByText(/keeps no document list for this kind/)).toBeTruthy()
  })

  it('nothing is listed until a kind is chosen', () => {
    draw('GPF')
    expect(screen.queryByText(/Documents required for/)).toBeNull()
  })
})

describe('what moved out of the third step', () => {
  it('the subscriber card asks for the name and nothing else', () => {
    draw('GPF')
    const third = card('3Subscriber')
    expect(within(third).getByLabelText("Subscriber's name")).toBeTruthy()
    expect(within(third).queryByLabelText(/Kind of claim/)).toBeNull()
    expect(within(third).queryByLabelText('Subscriber')).toBeNull()
  })

  it('gazetted stayed with the claim type, where it bears on the checks', () => {
    draw('GPF')
    expect(within(card('1Claim type')).getByLabelText('Subscriber')).toBeTruthy()
  })
})
