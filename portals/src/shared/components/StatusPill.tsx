import { STATUS_META, type CaseStatus } from '../api/cases'

export function StatusPill({ status, title }: { status: CaseStatus; title?: string }) {
  const m = STATUS_META[status] ?? { label: status, pill: 'neutral' }
  return <span className={`pill ${m.pill}`} title={title}>{m.label}</span>
}

export const statusLabelOf = (s: CaseStatus) => STATUS_META[s]?.label ?? s
