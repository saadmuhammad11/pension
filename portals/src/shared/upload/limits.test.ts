import { describe, expect, it } from 'vitest'
import { MAX_FILES, MAX_FILE_BYTES, checkFiles, progressWords } from './limits'

const f = (name: string, size = 1000) => ({ name, size })

describe('checkFiles (F8)', () => {
  it('skips a duplicate and says so, instead of dropping it silently', () => {
    const r = checkFiles([f('a.pdf')], [f('a.pdf'), f('b.pdf')])
    expect(r.accepted.map(x => x.name)).toEqual(['a.pdf', 'b.pdf'])
    expect(r.refused).toEqual(['a.pdf: already attached, skipped.'])
  })
  it('refuses an unknown type and a file over the size limit', () => {
    const r = checkFiles([], [f('notes.exe'), f('big.pdf', MAX_FILE_BYTES + 1), f('ok.PDF')])
    expect(r.accepted.map(x => x.name)).toEqual(['ok.PDF'])
    expect(r.refused[0]).toContain('not a document type')
    expect(r.refused[1]).toContain('over the 256 MB limit')
  })
  it('caps the number of files', () => {
    const many = Array.from({ length: MAX_FILES + 1 }, (_, i) => f(`p${i}.pdf`))
    const r = checkFiles([], many)
    expect(r.accepted).toHaveLength(MAX_FILES)
    expect(r.refused[0]).toContain(`at most ${MAX_FILES} files`)
  })
  it('words the progress in megabytes', () => expect(progressWords(5 * 1048576, 10 * 1048576)).toBe('5.0 MB of 10.0 MB sent'))
})
