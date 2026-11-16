import { useEffect, useRef, useState } from "react";

// Keeps one connection to the server's event stream and calls onEvent for
// each update. The browser reconnects by itself; `live` says whether the
// connection is currently up.
export function useLiveEvents(onEvent) {
  const [live, setLive] = useState(false);
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    const source = new EventSource("/api/events");
    const forward = (kind) => (event) => {
      let data = {};
      try {
        data = JSON.parse(event.data);
      } catch {
        // Ignore a malformed event.
      }
      handler.current(kind, data);
    };
    source.onopen = () => {
      setLive(true);
      // Anything might have changed while disconnected.
      handler.current("connected", {});
    };
    source.onerror = () => setLive(false);
    source.addEventListener("violation_created", forward("violation_created"));
    source.addEventListener("violation_updated", forward("violation_updated"));
    return () => source.close();
  }, []);

  return live;
}
