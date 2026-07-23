export type PollTask = (signal: AbortSignal) => Promise<void>;

export type SerialPoll = {
  start(): void;
  stop(): void;
  runNow(): Promise<void>;
};

/** Poll without ever allowing two executions of the task to overlap. */
export function createSerialPoll(task: PollTask, intervalMs: number): SerialPoll {
  let timer: number | undefined;
  let controller: AbortController | undefined;
  let stopped = true;
  let running: Promise<void> | undefined;

  const schedule = (): void => {
    if (stopped) return;
    timer = window.setTimeout(() => void runNow(), intervalMs);
  };

  const runNow = async (): Promise<void> => {
    if (stopped || running) return running;
    if (timer !== undefined) window.clearTimeout(timer);
    timer = undefined;
    controller = new AbortController();
    running = task(controller.signal);
    try {
      await running;
    } finally {
      running = undefined;
      controller = undefined;
      schedule();
    }
  };

  return {
    start() {
      if (!stopped) return;
      stopped = false;
      void runNow();
    },
    stop() {
      stopped = true;
      if (timer !== undefined) window.clearTimeout(timer);
      timer = undefined;
      controller?.abort();
    },
    runNow,
  };
}
