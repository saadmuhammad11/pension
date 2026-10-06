/** One portal's colours and words. Every value is a hex code or a string; nothing is computed. */
export interface Theme {
  /** The portal's short name in the <title> and the header. */
  title: string
  /** The line under it: whose office this is. */
  subtitle: string
  /** Urdu rendering of the title, shown beside it. */
  titleUrdu?: string
  /** Header, primary buttons, active states. Dark. */
  primary: string
  /** Hover and secondary emphasis. */
  primary2: string
  /** Rings, small accents. */
  primary3: string
  /** Light tints of the primary for backgrounds. */
  tint: string
  tint2: string
  /** The accent (gold on the AG portals): the pilot pill, the "gold" button, the crest ring. */
  accent: string
  accent2: string
  /** Text, secondary text, hairlines, page background. */
  ink: string
  muted: string
  line: string
  bg: string
}
