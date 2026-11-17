import {useEffect,useRef,useState} from 'react';
import {api,waitForResearch} from './lib/api.js';
import {validTicker} from './lib/format.js';
import {Dialog} from './components/Common.jsx';
import Market from './pages/Market.jsx';
import Chat from './pages/Chat.jsx';
import Forecast from './pages/Forecast.jsx';
import DeepResearch from './pages/DeepResearch.jsx';
import {Ledger,History} from './pages/Ledger.jsx';
import Connect from './pages/Connect.jsx';
import Method from './pages/Method.jsx';
import Trading from './pages/Trading.jsx';
const names={chat:'Research chat',forecast:'Forecast',research:'Research desk',deep:'Deep Research',trading:'Trading',memory:'Thesis ledger',runs:'Research history',connect:'Connect via MCP',method:'How it works'};
function NavIcon({name}) {
  if (name==='chat') return <svg className="nav-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M2 3.5h12v8H7l-3 2v-2H2z"/><path d="M5 6.5h6M5 9h4"/></svg>;
  if (name==='forecast') return <svg className="nav-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M2 2v12h12M4 11l3-4 3 2 4-5"/><path d="M11 4h3v3"/></svg>;
  if (name==='trading') return <svg className="nav-icon" viewBox="0 0 16 16" aria-hidden="true"><path d="M2 13h12M4 10V6M8 10V3M12 10V5"/></svg>;
  return {research:'◈',deep:'◇',memory:'▤',runs:'◷',connect:'⌘',method:'↳'}[name];
}
export default function App() {
  const [page,setPage]=useState(()=>names[location.hash.slice(1)] ? location.hash.slice(1) : 'research');
  const [config,setConfig]=useState(null),[configError,setConfigError]=useState(''),[auth,setAuth]=useState(false),[token,setToken]=useState('');
  const [ticker,setTicker]=useState('NVDA'),[chatTicker,setChatTicker]=useState('NVDA'),[report,setReport]=useState(null),[deepTicker,setDeepTicker]=useState('NVDA'),[researchStatus,setResearchStatus]=useState('Loading the latest live research…');
  const generation=useRef(0);
  function navigate(name) {if(name!==page)window.scrollTo(0,0);setPage(name);history.replaceState(null,'',location.pathname+location.search+'#'+name);}
  useEffect(()=>{const changed=()=>{const name=location.hash.slice(1);if(names[name])setPage(name);};const unlock=()=>setAuth(true);window.addEventListener('hashchange',changed);window.addEventListener('ledger-auth-required',unlock);return()=>{window.removeEventListener('hashchange',changed);window.removeEventListener('ledger-auth-required',unlock);};},[]);
  useEffect(()=>{const controller=new AbortController();api('/config',{signal:controller.signal}).then(setConfig).catch(e=>{if(!controller.signal.aborted)setConfigError(e.message);});return()=>controller.abort();},[]);
  useEffect(()=>{if(!config)return;const controller=new AbortController(),version=++generation.current;api('/dashboard?ticker='+encodeURIComponent(ticker),{signal:controller.signal}).then(saved=>{if(controller.signal.aborted || version!==generation.current)return;setReport(saved);setResearchStatus(saved ? `Saved live report · ${saved.request.as_of} · ${saved.snapshot.warnings.join(' ')}` : config.live_ready ? `Select Run research to generate a report for ${ticker}.` : 'Connect the research providers to run analysis.');}).catch(e=>{if(!controller.signal.aborted)setResearchStatus(e.message);});return()=>controller.abort();},[ticker,config]);
  function selectTicker(value){if(!validTicker(value))return;generation.current++;setTicker(value);setChatTicker(value);setDeepTicker(value);setReport(null);}
  async function openReport(id){const version=++generation.current;let saved=await api('/runs/'+encodeURIComponent(id));if(saved.status!=='complete')saved=await waitForResearch(await api('/runs/'+encodeURIComponent(id)+'/resume?background=true',{method:'POST'}),setResearchStatus);if(saved.status!=='complete')throw Error(saved.error || 'The research run did not complete.');if(version!==generation.current)return;setDeepTicker(saved.request.ticker);setReport(saved);setResearchStatus('Viewing saved research from '+saved.request.as_of+'.');navigate('deep');}
  return <><aside><a className="brand" href="/"><span className="mark">▥</span><span>thesis<span className="muted">ledger</span><small>RESEARCH WORKSPACE</small></span></a><div className="nav-caption">WORKSPACE</div><nav aria-label="Main navigation">{['chat','forecast','research','deep','trading','memory','runs'].map(name=><button key={name} data-page={name} className={page===name ? 'active' : ''} onClick={()=>navigate(name)}><NavIcon name={name}/><span>{names[name]}</span></button>)}</nav><div className="nav-caption">SYSTEM</div><nav>{['connect','method'].map(name=><button key={name} data-page={name} className={page===name ? 'active' : ''} onClick={()=>navigate(name)}><NavIcon name={name}/><span>{names[name]}</span>{name==='connect' && <span className="dot"/>}</button>)}</nav><div className="sidebar-bottom"><div className="avatar">HA</div>Independent research <span className="version">v0.1</span></div></aside><div className="workspace"><header><div><span className="muted">Workspace</span><span className="slash">/</span><span id="breadcrumb">{names[page]}</span></div><div id="account-controls" hidden={!config?.google_sign_in}><a id="google-signin" href="/auth/google" hidden={config?.signed_in}>Sign in with Google</a><form id="signout-form" action="/api/auth/logout" method="post" hidden={!config?.signed_in}><button className="secondary" type="submit">Sign out</button></form></div></header><p id="signin-status" className="info" role="status" hidden={!configError && new URLSearchParams(location.search).get('signin')!=='failed'}>{configError || 'Google sign-in did not finish. Please try again.'}</p>
  <Forecast active={page==='forecast'} ready={!!config} ticker={ticker}/><Chat active={page==='chat'} ready={!!config} ticker={chatTicker} onTicker={setChatTicker}/><Market active={page==='research'} ready={!!config} ticker={ticker} onSelect={selectTicker} onDeep={()=>navigate('deep')} report={report}/>
  <DeepResearch active={page==='deep'} config={config} ticker={deepTicker} onTicker={setDeepTicker} onSelect={selectTicker} report={report} onReport={setReport} status={researchStatus} onStatus={setResearchStatus} generation={generation}/>
  <Trading active={page==='trading'}/>
  <Ledger active={page==='memory'} config={config} onOpen={openReport} onDeep={()=>navigate('deep')}/><History active={page==='runs'} onOpen={openReport}/><Connect active={page==='connect'} config={config}/><Method active={page==='method'}/>
  <footer>THESIS LEDGER<span>Research software · No trade execution · Forecasts are uncertain</span></footer></div><Dialog id="auth-dialog" open={auth} onClose={()=>setAuth(false)}><form id="auth-form" onSubmit={event=>{event.preventDefault();if(token.trim()){sessionStorage.setItem('ledger-token',token.trim());location.reload();}}}><h2>Unlock Thesis Ledger</h2><p>Use the access token from this service’s Environment settings.</p><label htmlFor="access-token-input">Access token</label><input id="access-token-input" type="password" required autoComplete="off" value={token} onChange={e=>setToken(e.target.value)}/><div className="dialog-actions"><button type="button" id="close-auth" className="secondary" onClick={()=>setAuth(false)}>Cancel</button><button className="primary">Unlock</button></div></form></Dialog></>;
}
