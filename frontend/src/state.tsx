import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { api } from "./api";

export const Workspace = createContext({
  revision: 0,
  refresh: () => {},
  navigate: (_path: string) => {},
  dirty: false,
  setDirty: (_value: boolean) => {},
  notify: (_message: string) => {},
  markDirty: (_id: symbol, _value: boolean) => {},
});
export const useWorkspace = () => useContext(Workspace);

export function useResource<T>(
  path: string | null,
  poll = 0,
): { data?: T; error?: Error; loading: boolean; reload: () => void } {
  const { revision } = useWorkspace();
  const [state, setState] = useState<{
    data?: T;
    error?: Error;
    loading: boolean;
    path: string | null;
  }>({ loading: !!path, path });
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!path) {
      setState({ loading: false, path });
      return;
    }
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    let controller: AbortController;
    const load = async () => {
      controller = new AbortController();
      try {
        const data = await api<T>(path, { signal: controller.signal });
        if (alive) setState({ data, loading: false, path });
      } catch (error) {
        if (
          alive &&
          !(error instanceof DOMException && error.name === "AbortError")
        )
          setState((old) => ({
            data: old.path === path ? old.data : undefined,
            error: error as Error,
            loading: false,
            path,
          }));
      }
      if (alive && poll) timer = setTimeout(load, poll);
    };
    void load();
    return () => {
      alive = false;
      controller?.abort();
      clearTimeout(timer);
    };
  }, [path, revision, retry, poll]);
  return {
    ...(state.path === path ? state : { loading: !!path }),
    reload: () => setRetry((v) => v + 1),
  };
}

export function useAction() {
  const { refresh, notify } = useWorkspace();
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [error, setError] = useState<Error>();
  async function run(action: () => Promise<void>, success?: string) {
    if (lock.current) return;
    lock.current = true;
    setBusy(true);
    setError(undefined);
    try {
      await action();
      refresh();
      if (success) notify(success);
    } catch (e) {
      setError(e as Error);
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }
  return { busy, error, run, clearError: () => setError(undefined) };
}

export function useDirty() {
  const { markDirty } = useWorkspace();
  const token = useRef(Symbol());
  useEffect(() => () => markDirty(token.current, false), [markDirty]);
  return useCallback(
    (value: boolean) => markDirty(token.current, value),
    [markDirty],
  );
}
