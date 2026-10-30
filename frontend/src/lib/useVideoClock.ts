import { useEffect, useState } from "react";

/** Current time and play state of a <video>, updated smoothly (every frame while it plays). */
export function useVideoClock(video: HTMLVideoElement | null): { time: number; playing: boolean } {
  const [state, setState] = useState({ time: 0, playing: false });

  useEffect(() => {
    if (!video) {
      setState({ time: 0, playing: false });
      return;
    }
    let raf = 0;
    const sync = () => setState({ time: video.currentTime, playing: !video.paused && !video.ended });
    const loop = () => {
      sync();
      if (!video.paused && !video.ended) raf = requestAnimationFrame(loop);
    };
    const onPlay = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(loop);
    };
    const events = ["seeked", "seeking", "timeupdate", "pause", "ended", "loadedmetadata"] as const;
    for (const e of events) video.addEventListener(e, sync);
    video.addEventListener("play", onPlay);
    sync();
    if (!video.paused) onPlay();
    return () => {
      cancelAnimationFrame(raf);
      for (const e of events) video.removeEventListener(e, sync);
      video.removeEventListener("play", onPlay);
    };
  }, [video]);

  return state;
}
