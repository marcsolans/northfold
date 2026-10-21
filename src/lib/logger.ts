type LogLevel = "debug" | "info" | "warn" | "error";
type LogContext = Record<string, unknown>;

const LEVEL_ORDER: Record<LogLevel, number> = { debug: 10, info: 20, warn: 30, error: 40 };

// Tests only surface warnings and errors; everything else logs from "info" up.
const MIN_LEVEL: LogLevel = process.env.NODE_ENV === "test" ? "warn" : "info";

function serializeError(error: unknown): unknown {
  if (error instanceof Error) {
    return { name: error.name, message: error.message, stack: error.stack };
  }
  return error;
}

function write(level: LogLevel, message: string, context?: LogContext): void {
  if (LEVEL_ORDER[level] < LEVEL_ORDER[MIN_LEVEL]) return;
  const entry: LogContext = { level, time: new Date().toISOString(), msg: message };
  if (context) {
    for (const [key, value] of Object.entries(context)) {
      entry[key] = key === "error" || key === "err" ? serializeError(value) : value;
    }
  }
  // One JSON line per entry keeps logs greppable locally and structured on Vercel.
  const line = JSON.stringify(entry);
  if (level === "error") console.error(line);
  else if (level === "warn") console.warn(line);
  else console.info(line);
}

/** Structured JSON logger. The only module allowed to touch the console. */
export const logger = {
  debug: (message: string, context?: LogContext) => write("debug", message, context),
  info: (message: string, context?: LogContext) => write("info", message, context),
  warn: (message: string, context?: LogContext) => write("warn", message, context),
  error: (message: string, context?: LogContext) => write("error", message, context),
};
