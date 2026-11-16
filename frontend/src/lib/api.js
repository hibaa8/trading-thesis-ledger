export class ApiError extends Error {
  constructor(message, status, detail) { super(message); this.status = status; this.detail = detail; }
}
export async function apiResponse(path, options = {}) {
  const {tradingKey, ...init} = options;
  const privateRequest = path.startsWith('/trading');
  const token = privateRequest ? tradingKey : sessionStorage.getItem('ledger-token');
  const response = await fetch('/api' + path, {...init, headers: {
    'Content-Type': 'application/json', ...(token ? {Authorization:'Bearer ' + token} : {}), ...init.headers,
  }});
  if (response.status === 401 && !privateRequest) window.dispatchEvent(new Event('ledger-auth-required'));
  return response;
}
export async function api(path, options) {
  const response = await apiResponse(path, options);
  let data;
  try { data = await response.json(); }
  catch { throw new ApiError('The service returned an unexpected response. Your run may still be saved in Research History. Please retry shortly.', response.status); }
  if (!response.ok) throw new ApiError(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail) || 'The request could not complete.', response.status, data.detail);
  return data;
}
export function pause(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('Aborted', 'AbortError'));
    const finish = () => { signal?.removeEventListener('abort', cancel); resolve(); };
    const timer = setTimeout(finish, ms);
    const cancel = () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); };
    signal?.addEventListener('abort', cancel, {once:true});
  });
}
export async function waitForResearch(result, onProgress = () => {}, signal) {
  if (result.status !== 'running') return result;
  for (let attempt = 0; attempt < 100; attempt++) {
    await pause(3000, signal);
    const state = await api('/runs/' + encodeURIComponent(result.id) + '?status_only=true', {signal});
    if (state.status !== 'running') return api('/runs/' + encodeURIComponent(result.id), {signal});
    onProgress(`Researching… ${state.stages} agent stages saved. You can reopen this run from Research History.`);
  }
  throw Error('This run is taking longer than expected. Open Research History to check its saved progress.');
}
export async function* readChatStream(response) {
  if (!response.body) throw Error('The response was interrupted.');
  const reader = response.body.getReader(), decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const {value, done} = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, {stream:true});
      const lines = buffer.split('\n'); buffer = lines.pop();
      for (const line of lines) if (line.trim()) yield JSON.parse(line);
      if (done) { if (buffer.trim()) yield JSON.parse(buffer); break; }
    }
  } finally { try { await reader.cancel(); } finally { reader.releaseLock(); } }
}
export async function downloadReport(report, signal) {
  const response = await apiResponse('/runs/' + encodeURIComponent(report.id) + '/export?format=md', {signal});
  if (!response.ok) { let data; try { data = await response.json(); } catch {} throw Error(data?.detail || 'The report could not be exported.'); }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url; link.download = `thesis-ledger-${report.request.ticker}-${report.request.as_of}.md`;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
