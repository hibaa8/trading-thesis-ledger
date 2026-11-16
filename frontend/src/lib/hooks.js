import {useEffect, useState, useCallback} from 'react';
// Each resource owns its request and timer. Cleanup prevents stale ticker/page responses.
export function usePolling(load, enabled, interval = 30000) {
  const [state, setState] = useState({data:null, error:null, loading:false});
  const [version, setVersion] = useState(0);
  const refresh = useCallback(() => setVersion(value => value + 1), []);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController(); let timer;
    async function tick() {
      setState(previous => ({...previous, loading:true}));
      let value;
      try {
        value = await load(controller.signal);
        if (controller.signal.aborted) return;
        setState({data:value, error:null, loading:false});
      } catch (error) {
        if (controller.signal.aborted) return;
        setState(previous => ({...previous, error, loading:false}));
      }
      if (!controller.signal.aborted) timer = setTimeout(tick, typeof interval === 'function' ? interval(value) : interval);
    }
    tick();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [load, enabled, interval, version]);
  return {...state, refresh};
}
