export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const fmt = (n, digits = 2) => Number(n).toLocaleString('en-US', {minimumFractionDigits: digits, maximumFractionDigits: digits});
export const money = value => value == null ? 'Unavailable' : new Intl.NumberFormat('en-US', {style:'currency', currency:'USD'}).format(Number(value));
export const time = value => value ? new Date(value).toLocaleString() : 'Unknown';
export const label = value => String(value || 'unknown').replaceAll('_', ' ');
export const tone = value => Number(value) > 0 ? 'positive' : Number(value) < 0 ? 'negative' : '';
export const validTicker = value => /^[A-Z][A-Z0-9.\-]{0,9}$/.test(value);
export const localDate = () => new Date().toLocaleDateString('en-CA');
export function safeUrl(value) { try { const u = new URL(value); return ['https:', 'http:'].includes(u.protocol) ? u.href : null; } catch { return null; } }
