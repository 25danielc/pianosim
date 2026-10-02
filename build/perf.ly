\version "2.26.0"
\include "articulate.ly"
\include "defs.ly"
% Trill speed: one upper/lower pair per 1/12 whole note (sextuplet 16ths,
% ~17 notes/s at half = 84) instead of articulate.ly's fixed 1/64.
#(define (ac:twiddletime music) 1/12)
% Performance MIDI: same notes as the Mutopia engraving, plus the score's own
% pedal marks (\sustain voice) and a real tempo (half = 84, inside the music so
% articulate.ly paces the trills from it). Velocities come from the score's
% dynamics in build/perform.py.
\score {
  \articulate
  \context PianoStaff <<
    \context Staff = "up" <<
      \set Staff.midiInstrument = #"acoustic grand"
      { \tempo 4 = 168 \topmain } \topsecondary
    >>
    \context Staff = "down" <<
      \set Staff.midiInstrument = #"acoustic grand"
      \bottom \bottomsecondary \sustain
    >>
  >>
  \midi { \context { \Voice \remove Dynamic_performer } }
}
