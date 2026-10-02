\version "2.26.0"
\include "event-listener-text.ly"
\include "defs.ly"
\score {
  \context PianoStaff <<
    \context Staff = "up" <<
      \set Staff.instrumentName = "up"
      \topmain \topsecondary
    >>
    \context Staff = "down" <<
      \set Staff.instrumentName = "down"
      \bottom \bottomsecondary
    >>
  >>
  \layout { }
}
