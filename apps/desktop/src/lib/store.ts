// Minimal external store + React binding via useSyncExternalStore.
// Components select narrow slices so 10 Hz state frames only re-render what
// actually reads the state frame.
import { useSyncExternalStore } from "react";

export type Listener = () => void;

export class Store<S, A> {
  private listeners = new Set<Listener>();

  constructor(
    private readonly reducer: (s: S, a: A) => S,
    private state: S,
  ) {}

  getState = (): S => this.state;

  dispatch = (action: A): void => {
    const next = this.reducer(this.state, action);
    if (next === this.state) return;
    this.state = next;
    for (const l of [...this.listeners]) l();
  };

  subscribe = (listener: Listener): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
}

/** Subscribe a component to a slice. The selector must return a stable value. */
export function useStore<S, A, T>(store: Store<S, A>, selector: (s: S) => T): T {
  return useSyncExternalStore(store.subscribe, () => selector(store.getState()));
}
