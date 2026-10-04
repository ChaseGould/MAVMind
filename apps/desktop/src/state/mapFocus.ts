// Tiny bus so panels (e.g. a proposal card) can ask the map to fit a set of points.
export type FocusRequest = { points: [number, number][] };
type Handler = (r: FocusRequest) => void;

const handlers = new Set<Handler>();

export const mapFocus = {
  emit(r: FocusRequest) {
    for (const h of handlers) h(r);
  },
  on(h: Handler): () => void {
    handlers.add(h);
    return () => {
      handlers.delete(h);
    };
  },
};
