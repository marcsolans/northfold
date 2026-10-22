/**
 * Browser audio for voice calls in audio mode: microphone → PCM16 mono 16 kHz chunks, and gapless playback of
 * PCM16 16 kHz chunks with the cumulative "played" position the voice protocol acknowledges.
 */

export const VOICE_SAMPLE_RATE = 16_000;

type AudioContextCtor = typeof AudioContext;

function audioContextCtor(): AudioContextCtor {
  const w = window as unknown as { AudioContext?: AudioContextCtor; webkitAudioContext?: AudioContextCtor };
  const ctor = w.AudioContext ?? w.webkitAudioContext;
  if (!ctor) throw new Error("audio_unsupported");
  return ctor;
}

export function audioSupported(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as unknown as { AudioContext?: unknown; webkitAudioContext?: unknown };
  const devices = navigator.mediaDevices as MediaDevices | undefined;
  return Boolean(devices && typeof devices.getUserMedia === "function" && (w.AudioContext ?? w.webkitAudioContext));
}

/** Average-decimate float samples from ``from`` Hz to ``to`` Hz and convert to PCM16. */
export function downsampleToPcm16(input: Float32Array, from: number, to: number): Int16Array {
  const ratio = from / to;
  const length = Math.floor(input.length / ratio);
  const out = new Int16Array(length);
  let pos = 0;
  for (let i = 0; i < length; i++) {
    const end = Math.min(input.length, Math.round((i + 1) * ratio));
    let sum = 0;
    let count = 0;
    for (; pos < end; pos++) {
      sum += input[pos] ?? 0;
      count++;
    }
    const sample = Math.max(-1, Math.min(1, count ? sum / count : 0));
    out[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return out;
}

export class MicCapture {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private node: ScriptProcessorNode | null = null;
  muted = false;

  constructor(private readonly onChunk: (pcm: ArrayBuffer) => void) {}

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    const Ctor = audioContextCtor();
    const ctx = new Ctor();
    this.ctx = ctx;
    if (ctx.state === "suspended") await ctx.resume();
    this.source = ctx.createMediaStreamSource(this.stream);
    // ScriptProcessor keeps the capture path free of extra module scripts (strict CSP); ~85 ms per buffer at 48 kHz.
    this.node = ctx.createScriptProcessor(4096, 1, 1);
    this.node.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0);
      const pcm = downsampleToPcm16(input, ctx.sampleRate, VOICE_SAMPLE_RATE);
      if (this.muted) pcm.fill(0);
      this.onChunk(pcm.buffer as ArrayBuffer);
    };
    this.source.connect(this.node);
    this.node.connect(ctx.destination);
  }

  stop(): void {
    this.node?.disconnect();
    this.source?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    void this.ctx?.close().catch(() => undefined);
    this.node = null;
    this.source = null;
    this.stream = null;
    this.ctx = null;
  }
}

interface Scheduled {
  source: AudioBufferSourceNode;
  start: number;
  end: number;
}

export class PcmPlayer {
  private ctx: AudioContext | null = null;
  private nextTime = 0;
  private scheduled: Scheduled[] = [];
  private completedMs = 0;

  async start(): Promise<void> {
    const Ctor = audioContextCtor();
    this.ctx = new Ctor();
    if (this.ctx.state === "suspended") await this.ctx.resume();
  }

  /** Queue base64 PCM16 mono 16 kHz audio right after what is already scheduled. */
  enqueue(base64: string): void {
    const ctx = this.ctx;
    if (!ctx) return;
    const raw = atob(base64);
    const samples = Math.floor(raw.length / 2);
    if (!samples) return;
    const buffer = ctx.createBuffer(1, samples, VOICE_SAMPLE_RATE);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < samples; i++) {
      const lo = raw.charCodeAt(2 * i);
      const hi = raw.charCodeAt(2 * i + 1);
      let value = (hi << 8) | lo;
      if (value >= 0x8000) value -= 0x10000;
      channel[i] = value / 0x8000;
    }
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    const start = Math.max(ctx.currentTime + 0.02, this.nextTime);
    source.start(start);
    this.nextTime = start + buffer.duration;
    this.scheduled.push({ source, start, end: this.nextTime });
  }

  private settle(now: number): void {
    while (this.scheduled.length && (this.scheduled[0]?.end ?? Infinity) <= now) {
      const done = this.scheduled.shift();
      if (done) this.completedMs += (done.end - done.start) * 1000;
    }
  }

  /** Cumulative milliseconds actually played this session (interrupted audio excluded). */
  playedMs(): number {
    const ctx = this.ctx;
    if (!ctx) return this.completedMs;
    const now = ctx.currentTime;
    this.settle(now);
    const head = this.scheduled[0];
    const partial = head && now > head.start ? (now - head.start) * 1000 : 0;
    return Math.round(this.completedMs + partial);
  }

  isPlaying(): boolean {
    const ctx = this.ctx;
    if (!ctx) return false;
    this.settle(ctx.currentTime);
    return this.scheduled.length > 0;
  }

  /** Barge-in: drop everything not yet heard. */
  clear(): void {
    const ctx = this.ctx;
    if (!ctx) return;
    const now = ctx.currentTime;
    this.settle(now);
    for (const item of this.scheduled) {
      if (now > item.start) this.completedMs += (Math.min(now, item.end) - item.start) * 1000;
      try {
        item.source.stop();
      } catch {
        // already stopped
      }
    }
    this.scheduled = [];
    this.nextTime = now;
  }

  stop(): void {
    this.clear();
    void this.ctx?.close().catch(() => undefined);
    this.ctx = null;
  }
}
