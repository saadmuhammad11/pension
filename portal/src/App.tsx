import { useEffect, useState } from 'react'
import './tokens.css'
import { Header } from './components/Header'
import { Stepper } from './components/Stepper'
import { Cases } from './screens/Cases'
import { Intake } from './screens/Intake'
import { Analysis } from './screens/Analysis'
import { Review } from './screens/Review'
import { Decision } from './screens/Decision'
import { apiAvailable, fetchReport, type Role } from './api'
import type { CaseReport } from './types'

/** Where the portal is. The register is home; a case is opened out of it and closed back
 *  into it. The stepper still describes the four stages of working a single case, so it
 *  appears only while one is open. */
type View = 'register' | 'intake' | 'analysis' | 'review' | 'decision'

const STEP_OF: Partial<Record<View, number>> = {
  intake: 0, analysis: 1, review: 2, decision: 3,
}

export default function App() {
  const [view, setView] = useState<View>('register')
  const [role, setRole] = useState<Role>('ACCOUNTS_OFFICE')
  const [runId, setRunId] = useState<string | null>(null)
  const [report, setReport] = useState<CaseReport | null>(null)
  const [online, setOnline] = useState<boolean | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { apiAvailable().then(setOnline) }, [])

  async function openReport(id: string, next: View = 'review') {
    setError(null)
    try {
      setReport(await fetchReport(id))
      setRunId(id)
      setView(next)
    } catch (e) {
      setError(`Case ${id.toUpperCase()} could not be opened: ${e}`)
    }
  }

  function backToRegister() {
    setView('register'); setRunId(null); setReport(null); setError(null)
  }

  if (online === false) {
    return (
      <>
        <Header role={role} onRole={setRole} onNew={() => setView('intake')} />
        <div className="container" style={{ paddingTop: 40 }}>
          <div className="card" style={{ borderColor: 'var(--amber)', background: 'var(--amberbg)' }}>
            <h3 style={{ marginTop: 0 }}>The pipeline API is not reachable</h3>
            <p>
              This portal does not simulate a run. Without the API there is nothing to show,
              which is deliberate: a screen that animates without doing the work is worse than
              a screen that says it cannot.
            </p>
            <p className="mono" style={{ fontSize: 12 }}>
              /home/tmc/vllm_env/bin/python3 -m api.server 8100
            </p>
          </div>
        </div>
      </>
    )
  }

  const step = STEP_OF[view]

  return (
    <>
      <Header role={role} onRole={setRole} onNew={() => setView('intake')} />
      {step !== undefined && <Stepper current={step} />}

      {view !== 'register' && (
        <div className="container" style={{ paddingTop: 14, display: 'flex', gap: 'var(--s3)' }}>
          <button className="ghost" onClick={backToRegister}>← Case register</button>
        </div>
      )}

      {error && (
        <div className="container" style={{ paddingTop: 12 }}>
          <div className="card" style={{ borderColor: 'var(--red)', background: 'var(--redbg)', color: 'var(--red)' }}>{error}</div>
        </div>
      )}

      {view === 'register' && (
        <Cases
          role={role}
          onOpen={id => openReport(id)}
          onNew={() => setView('intake')}
        />
      )}
      {view === 'intake' && (
        <Intake role={role} onStarted={id => { setRunId(id); setView('analysis') }} />
      )}
      {view === 'analysis' && runId && (
        <Analysis runId={runId} onDone={() => openReport(runId)} />
      )}
      {view === 'review' && report && runId && (
        <Review report={report} runId={runId} role={role}
                onProceed={() => setView('decision')} />
      )}
      {view === 'decision' && report && runId && (
        <Decision report={report} runId={runId} role={role} onReset={backToRegister}
          onNew={() => { setRunId(null); setReport(null); setView('intake') }} />
      )}
    </>
  )
}
