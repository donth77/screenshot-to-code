// When to post `rn-preview:update` to a preview iframe (DESIGN.md §5.5).
//
// The iframe loads the runtime once (about 4.7 MB of script) and then
// re-renders by message. The runtime only listens once it has booted, and a
// render takes tens of milliseconds, so the channel:
//   - sends nothing until the document reports its first render;
//   - keeps one update in flight and always sends the newest request next,
//     skipping any the frame never needed to see (streaming code arrives far
//     faster than it renders);
//   - treats a status with renderId 1 as a freshly booted document, which
//     renders the request its HTML was built with (a reload by anyone);
//   - gives up waiting for a lost status after a timeout.
import type { DeviceProfile, PreviewMode } from "./previewHtml";

export interface PreviewRequest {
  source: string;
  profile: DeviceProfile;
  mode: PreviewMode;
}

export function requestKey({ source, profile, mode }: PreviewRequest): string {
  return `${mode}\n${JSON.stringify(profile)}\n${source}`;
}

export class HotSwapChannel {
  private booted = false;
  private inflight = false;
  private sentAt = 0;
  private sentKey = "";
  private documentKey = "";
  private desired: PreviewRequest | null = null;

  constructor(
    private readonly send: (request: PreviewRequest) => void,
    private readonly now: () => number = () => Date.now(),
    private readonly timeoutMs = 10_000
  ) {}

  // The frame's document was (re)built with this request in its config.
  loaded(request: PreviewRequest): void {
    this.desired = request;
    this.documentKey = this.sentKey = requestKey(request);
    this.booted = false;
    this.inflight = true;
  }

  // The app wants this rendered.
  want(request: PreviewRequest): void {
    this.desired = request;
    this.flush();
  }

  // The frame finished a render.
  rendered(renderId: number): void {
    if (renderId === 1) this.sentKey = this.documentKey;
    this.booted = true;
    this.inflight = false;
    this.flush();
  }

  private flush(): void {
    if (!this.desired || !this.booted) return;
    if (this.inflight && this.now() - this.sentAt < this.timeoutMs) return;
    const key = requestKey(this.desired);
    if (key === this.sentKey) return;
    this.sentKey = key;
    this.inflight = true;
    this.sentAt = this.now();
    this.send(this.desired);
  }
}
