# TRANSCRIPT (also required in this run)

In addition to the fields, the JSON object contains a `transcript`: the whole conversation as dialogue turns, in order.

**Write the transcript first, then fill the fields from it.** The transcript is your working text: every value in `fields` must be supported by a line in it, and every `evidence` quote and `timestamp` must point to a line that exists in it.

Rules for each turn (`speaker`, `time`, `text`):

- `speaker`: `CEX` for the iFarmer agent who made the call, `farmer` for the farmer, `other` for anyone else (spouse, relative, bystander; say who in the text if clear, e.g. `[wife]`). Keep the same label for the same person throughout.
- `time`: when the turn **starts**, formatted `HH:MM:SS` (e.g. `00:00:07`, `00:12:41`). Times must never go backwards. Use the audio's own clock, starting at `00:00:00`, and keep it consistent for the whole recording. Do not let times drift on long calls: re-check against what you hear near the end.
- `text`: what was said, in **Banglish** (Bangla written in English letters the way a Bangladeshi types it on a phone), for example `as salam oa alaikum, ami ifarmer theke bolchi.` Rules:
  - Keep the speaker's own words and dialect; do not rephrase, summarise or "correct" them.
  - Keep numbers as they were said, e.g. `chollish hajar`, not `40000`. English words stay in English.
  - Use `[inaudible]` for words you cannot make out. Never fill the gap with a guess.
  - Do not translate to English and do not use Bangla script.
- One turn per speaker change. Do not merge two speakers into one turn. Include greetings, fillers that carry meaning, and the closing, but leave out long silences, hold music and ringing.
- If the recording has no speech at all, return an empty `transcript` and say so in `warnings`.
