/** The footer on every page: just the "Powered by TMC" mark (design of 28 Sep 2026). */
export function Footer() {
  return (
    <footer className="site-footer">
      <div className="container site-footer-row">
        <a className="powered" href="https://tmcltd.com/" target="_blank" rel="noreferrer" title="TallyMarks Consulting">
          <span>Powered by</span>
          <img src="./tmc-logo.png" alt="TMC — TallyMarks Consulting" />
        </a>
      </div>
    </footer>
  )
}
