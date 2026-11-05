import {
  ReactNode,
  useEffect,
  useState,
  useSyncExternalStore,
} from 'react';
import {
  type AudioButtonState,
  type ClipJob,
  getAudioSnapshot,
  startPlayback,
  subscribeAudio,
} from '../audio';

export interface AudioButtonProps {
  jobs: ClipJob[];
  /** Button content — '▶' per item/date, '▶ Play all news'. */
  children?: ReactNode;
  className?: string;
}

/**
 * One ▶ trigger — a click replaces the global play queue
 * (audio.ts resolves each clip through the shared pool, drops
 * failures, plays in order). The ⏳/⚠ transient states ride
 * `data-state` (news.css); they reset when the ■ Stop button
 * bumps the snapshot's resetSeq — the old script's
 * `.audio-btn[data-state]` sweep.
 */
export default function AudioButton({
  jobs,
  children = '▶',
  className,
}: AudioButtonProps) {
  const [state, setState] = useState<AudioButtonState>(null);
  const { resetSeq } = useSyncExternalStore(
    subscribeAudio,
    getAudioSnapshot,
  );

  useEffect(() => {
    setState(null);
  }, [resetSeq]);

  return (
    <button
      type="button"
      className={className ?? 'audio-btn'}
      data-state={state ?? undefined}
      onClick={() => startPlayback(jobs, setState)}
    >
      {children}
    </button>
  );
}
