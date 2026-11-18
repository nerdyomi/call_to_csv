/** Question text and option labels from the real form export (regenerate with scripts/export_form_labels.py). */
import raw from "./formLabels.json";

interface Q {
  order: number;
  label: string;
  section: string;
  type: string;
  options: string[][];
}
const fields = (raw as { fields: Record<string, Q> }).fields;

export const formVersion = (raw as { formVersion: string }).formVersion;

export function question(key: string): Q | undefined {
  return fields[key];
}

/** The Bangla question the agent asks for this key, or "" when the key is not in the form (older results). */
export function questionLabel(key: string): string {
  return fields[key]?.label ?? "";
}

export function formOrder(key: string): number {
  return fields[key]?.order ?? 9999;
}

/** 'bigha' -> 'বিঘা'; several codes ('own, lease_mortgage') are translated one by one. Unknown values are returned as they are. */
export function valueLabel(key: string, value: string): string {
  const opts = fields[key]?.options;
  if (!opts?.length) return value;
  return value
    .split(",")
    .map((v) => v.trim())
    .map((v) => opts.find(([code]) => code === v)?.[1] ?? v)
    .join(", ");
}
