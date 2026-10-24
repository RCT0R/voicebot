const E164 = /^\+[1-9]\d{7,14}$/;

export function normalizeE164(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const cleaned = value.trim().replace(/[\s().-]/g, '');
  return E164.test(cleaned) ? cleaned : null;
}

export function clampText(value: unknown, limit: number): string {
  return typeof value === 'string' ? value.trim().slice(0, limit) : '';
}
