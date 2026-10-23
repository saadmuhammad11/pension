/** The pension case types, from the one file the whole system shares (config/case_types.json,
 *  29 Sep 2026): the eleven columns of the AG office's document sheet (Document Checklist.pdf), each
 *  also the checklist column the case runs on. rules/case_type.py derives its tables from the same
 *  file, so what a DDO picks from here is exactly what the rules run on. The pipeline's own paths
 *  (what the AI reads a bundle as) are listed too, for labelling what it detected. */
import config from '../../../config/case_types.json'

export interface CaseTypeDef {
  id: string
  label: string
  family: 'SELF_PENSION' | 'FAMILY_PENSION'
  /** The PSA form the sheet expects; null for a revision, which carries the original's form. */
  prescribed_form: string | null
  /** The pipeline path(s) this type may be; empty means any. */
  pipeline_types: string[]
  hint: string
}

type Config = { case_types: CaseTypeDef[]; pipeline_types: { id: string; label: string; prescribed_form: string }[]; aliases?: Record<string, string> }
const CFG = config as Config
export const CASE_TYPE_LIST: CaseTypeDef[] = CFG.case_types
const BY_ID = new Map(CASE_TYPE_LIST.map(t => [t.id, t]))
const PIPELINE_LABELS = new Map(CFG.pipeline_types.map(t => [t.id, t.label]))
const ALIASES: Record<string, string> = CFG.aliases ?? {}
/** A label for either kind of id: an office case type, or the pipeline path the AI detected. */
export const anyCaseTypeLabel = (id: string | null | undefined): string | undefined =>
  id ? (BY_ID.get(id)?.label ?? PIPELINE_LABELS.get(ALIASES[id] ?? id)) : undefined

/** Where the type came from, in the words the screens use. */
export const CASE_TYPE_SOURCE_WORDS: Record<string, string> = {
  DECLARED: 'Declared by the DDO', CORRECTED: 'Corrected by the Office of the Accountant General', DETECTED: 'Detected by the AI',
}
/* caseTypeSourceShort -- "Declared", "Detected", "Corrected" -- was written for the one-line
   form the case particulars used, and the case particulars are gone (22 Oct 2026). The long
   words above are what the case-type panel says and are the only form left. */
