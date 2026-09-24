import { HotSwapChannel, PreviewRequest } from "./hotSwap";

const PROFILE = {
  platform: "ios" as const,
  width: 390,
  height: 763,
  scale: 3,
  insets: { top: 0, right: 0, bottom: 0, left: 0 },
};

function request(source: string, mode: PreviewRequest["mode"] = "final"): PreviewRequest {
  return { source, profile: PROFILE, mode };
}

function setup() {
  const sent: string[] = [];
  let clock = 0;
  const channel = new HotSwapChannel(
    (r) => sent.push(`${r.mode}:${r.source}`),
    () => clock,
    10_000
  );
  return { channel, sent, advance: (ms: number) => (clock += ms) };
}

describe("HotSwapChannel", () => {
  test("waits for the document to boot, then sends only what changed", () => {
    const { channel, sent } = setup();
    channel.loaded(request("a"));
    channel.want(request("b"));
    expect(sent).toEqual([]); // the runtime isn't listening yet
    channel.rendered(1);
    expect(sent).toEqual(["final:b"]);
    channel.rendered(2);
    channel.want(request("b"));
    expect(sent).toEqual(["final:b"]);
  });

  test("keeps one update in flight and sends the newest next", () => {
    const { channel, sent } = setup();
    channel.loaded(request("a", "streaming"));
    channel.rendered(1);
    channel.want(request("ab", "streaming"));
    channel.want(request("abc", "streaming"));
    channel.want(request("abcd", "streaming"));
    expect(sent).toEqual(["streaming:ab"]);
    channel.rendered(2);
    expect(sent).toEqual(["streaming:ab", "streaming:abcd"]);
  });

  test("a mode change alone is an update", () => {
    const { channel, sent } = setup();
    channel.loaded(request("a", "streaming"));
    channel.rendered(1);
    channel.want(request("a", "final"));
    expect(sent).toEqual(["final:a"]);
  });

  test("a reload re-renders the document's own request, then catches up", () => {
    const { channel, sent } = setup();
    channel.loaded(request("a"));
    channel.rendered(1);
    channel.want(request("b"));
    channel.rendered(2);
    expect(sent).toEqual(["final:b"]);
    // Someone reloads the iframe: its document boots with "a" again.
    channel.rendered(1);
    expect(sent).toEqual(["final:b", "final:b"]);
  });

  test("resends after a lost status once the timeout passes", () => {
    const { channel, sent, advance } = setup();
    channel.loaded(request("a"));
    channel.rendered(1);
    channel.want(request("b"));
    channel.want(request("c"));
    expect(sent).toEqual(["final:b"]);
    advance(10_001);
    channel.want(request("d"));
    expect(sent).toEqual(["final:b", "final:d"]);
  });

  test("a stale status before the new document boots is recovered", () => {
    const { channel, sent } = setup();
    channel.loaded(request("a"));
    channel.rendered(1);
    channel.loaded(request("b")); // refresh with newer code
    channel.rendered(7); // late status from the old document
    channel.want(request("c"));
    expect(sent).toEqual(["final:c"]); // may be lost: the new document isn't listening
    channel.rendered(1); // the new document booted with "b"
    expect(sent).toEqual(["final:c", "final:c"]);
  });
});
