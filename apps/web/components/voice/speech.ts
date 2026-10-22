/**
 * Web Speech API wrappers for demo (text) mode and browser dictation: continuous recognition with interim
 * results, and a speech-synthesis queue that reports progress in the voice protocol's "played" milliseconds.
 */

interface RecognitionAlternative {
  transcript: string;
}

interface RecognitionResult {
  readonly isFinal: boolean;
  readonly length: number;
  [index: number]: RecognitionAlternative;
}

interface RecognitionEvent {
  readonly resultIndex: number;
  readonly results: { readonly length: number; [index: number]: RecognitionResult };
}

interface RecognitionErrorEvent {
  readonly error: string;
}

interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: RecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

type RecognitionCtor = new () => SpeechRecognitionLike;

function recognitionCtor(): RecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function speechRecognitionAvailable(): boolean {
  return recognitionCtor() !== null;
}

export function speechSynthesisAvailable(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window && typeof SpeechSynthesisUtterance !== "undefined";
}

/** Fatal recognition errors (the user or the browser said no); others are retried by restarting. */
const FATAL_ERRORS = new Set(["not-allowed", "service-not-allowed", "audio-capture", "language-not-supported"]);

export class BrowserRecognizer {
  private recognition: SpeechRecognitionLike | null = null;
  private active = false;

  constructor(
    private readonly lang: string,
    private readonly handlers: {
      onPartial: (text: string) => void;
      onFinal: (text: string) => void;
      onError: (code: string) => void;
    },
  ) {}

  start(): void {
    const Ctor = recognitionCtor();
    if (!Ctor) {
      this.handlers.onError("unsupported");
      return;
    }
    this.active = true;
    const recognition = new Ctor();
    recognition.lang = this.lang;
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        const text = result?.[0]?.transcript ?? "";
        if (!result || !text.trim()) continue;
        if (result.isFinal) this.handlers.onFinal(text.trim());
        else interim += text;
      }
      if (interim.trim()) this.handlers.onPartial(interim.trim());
    };
    recognition.onerror = (event) => {
      if (FATAL_ERRORS.has(event.error)) {
        this.active = false;
        this.handlers.onError(event.error);
      }
    };
    recognition.onend = () => {
      // Browsers end continuous recognition on long silences; keep listening while the call is live.
      if (this.active) {
        try {
          recognition.start();
        } catch {
          this.active = false;
        }
      }
    };
    this.recognition = recognition;
    recognition.start();
  }

  stop(): void {
    this.active = false;
    try {
      this.recognition?.stop();
    } catch {
      // not started
    }
    this.recognition = null;
  }
}

interface Segment {
  segment: number;
  text: string;
  durationMs: number;
}

/**
 * Speaks the segments the voice service sends in text mode, in order. ``playedMs`` advances by each segment's
 * server-side duration when it finishes (or by the elapsed share when cut), so acknowledgements stay on the
 * same axis the server paces.
 */
export class BrowserSpeaker {
  private queue: Segment[] = [];
  private current: { segment: Segment; startedAt: number; token: number } | null = null;
  private token = 0;
  private completedMs = 0;

  constructor(
    private readonly lang: string,
    private readonly voiceName: string | null,
    private readonly onIdle: () => void,
  ) {}

  enqueue(segment: Segment): void {
    this.queue.push(segment);
    if (!this.current) this.speakNext();
  }

  speaking(): boolean {
    return this.current !== null || this.queue.length > 0;
  }

  playedMs(): number {
    if (!this.current) return Math.round(this.completedMs);
    const elapsed = Math.min(this.current.segment.durationMs, performance.now() - this.current.startedAt);
    return Math.round(this.completedMs + elapsed);
  }

  private pickVoice(): SpeechSynthesisVoice | null {
    const voices = window.speechSynthesis.getVoices();
    if (this.voiceName) {
      const chosen = voices.find((v) => v.name === this.voiceName);
      if (chosen) return chosen;
    }
    const prefix = this.lang.slice(0, 2).toLowerCase();
    return voices.find((v) => v.lang.toLowerCase() === this.lang.toLowerCase()) ?? voices.find((v) => v.lang.toLowerCase().startsWith(prefix)) ?? null;
  }

  private speakNext(): void {
    const next = this.queue.shift();
    if (!next) {
      this.current = null;
      this.onIdle();
      return;
    }
    const token = ++this.token;
    this.current = { segment: next, startedAt: performance.now(), token };
    const utterance = new SpeechSynthesisUtterance(next.text);
    utterance.lang = this.lang;
    const voice = this.pickVoice();
    if (voice) utterance.voice = voice;
    const finish = () => {
      if (!this.current || this.current.token !== token) return;
      this.completedMs += next.durationMs;
      this.current = null;
      this.speakNext();
    };
    utterance.onend = finish;
    utterance.onerror = finish;
    window.speechSynthesis.speak(utterance);
  }

  /** Barge-in or a new user turn: stop speaking and drop what was not said. */
  cancel(): void {
    if (this.current) {
      this.completedMs += Math.min(this.current.segment.durationMs, performance.now() - this.current.startedAt);
    }
    this.token++;
    this.current = null;
    this.queue = [];
    window.speechSynthesis.cancel();
  }
}
