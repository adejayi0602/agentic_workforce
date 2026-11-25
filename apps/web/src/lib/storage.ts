/**
 * Browser storage that never throws. Private modes and sandboxed frames can refuse access;
 * the app then keeps state in memory for the life of the tab.
 */

const memory = new Map<string, string>();

function store(kind: "session" | "local"): Storage | null {
  try {
    return kind === "session" ? window.sessionStorage : window.localStorage;
  } catch {
    return null;
  }
}

export function read(kind: "session" | "local", key: string): string | null {
  try {
    return store(kind)?.getItem(key) ?? memory.get(`${kind}:${key}`) ?? null;
  } catch {
    return memory.get(`${kind}:${key}`) ?? null;
  }
}

export function write(kind: "session" | "local", key: string, value: string | null): void {
  const memoryKey = `${kind}:${key}`;
  if (value === null) memory.delete(memoryKey);
  else memory.set(memoryKey, value);
  try {
    if (value === null) store(kind)?.removeItem(key);
    else store(kind)?.setItem(key, value);
  } catch {
    // Memory copy above is enough.
  }
}
