/** F14: one password rule, told by the server; a live checklist and a Show toggle. */
import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { PasswordField, passwordChecks } from '../PasswordField'

describe('PasswordField', () => {
  it('checks the server\'s minimum, the username, and a trivial run', () => {
    expect(passwordChecks('short', 10, 'ali').map(c => c.ok)).toEqual([false, true, true])
    expect(passwordChecks('ali-is-great-99', 10, 'ali')[1].ok).toBe(false)
    expect(passwordChecks('aaaaaaaaaaaa', 10)[2].ok).toBe(false)
    expect(passwordChecks('Correct Horse 7', 10, 'ali').every(c => c.ok)).toBe(true)
  })
  it('uses the minimum it is given and toggles Show', () => {
    const onChange = vi.fn()
    render(<PasswordField id="pw" label="Password" value="abc" onChange={onChange} minLength={12} username="x" />)
    expect(screen.getByText('At least 12 characters')).toBeInTheDocument()
    const input = screen.getByLabelText('Password') as HTMLInputElement
    expect(input.type).toBe('password')
    fireEvent.click(screen.getByRole('button', { name: 'Show password' }))
    expect(input.type).toBe('text')
  })
})
