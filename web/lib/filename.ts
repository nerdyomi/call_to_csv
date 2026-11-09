/** Phone number + call date from a recording file name, same rules as the Python pipeline. */
const AUDIO_EXT = /\.(mp3|mpeg|mpga|wav|m4a|aac|ogg|flac)$/i;

export function stripAudioExtensions(name: string): string {
  let s = name;
  while (AUDIO_EXT.test(s)) s = s.replace(AUDIO_EXT, "");
  return s;
}

export function normalizePhone(input: string): string | null {
  const digits = input.replace(/\D/g, "");
  const m = digits.match(/^(?:88)?(0?1\d{9})$/);
  if (!m) return null;
  return "88" + (m[1].startsWith("0") ? m[1] : "0" + m[1]);
}

export interface ParsedName {
  phone: string | null;
  date: string | null;
}

/** 20261101-183111_IFARMER__4004_01727641576-all.mp3 -> {phone: 8801727641576, date: 2026-11-01} */
export function parseRecordingName(fileName: string): ParsedName {
  const stem = stripAudioExtensions(fileName);
  const m = stem.match(/^(?:(\d{4})(\d{2})(\d{2})-\d{6}_.*?_)?(0?1\d{9})(?:-.*)?$/);
  if (!m) {
    const loose = stem.match(/(0?1\d{9})/);
    return { phone: loose ? normalizePhone(loose[1]) : null, date: null };
  }
  const date = m[1] ? `${m[1]}-${m[2]}-${m[3]}` : null;
  return { phone: normalizePhone(m[4]), date: date && isValidDate(date) ? date : null };
}

export function isValidDate(s: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return false;
  const d = new Date(s + "T00:00:00Z");
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s;
}

/** Storage keys must be plain ASCII; the original name is kept in the database. */
export function safeStorageName(name: string): string {
  return name.replace(/[^\w.\-]+/g, "_");
}
