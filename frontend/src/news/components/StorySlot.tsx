import { ReactNode, useId, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchStoryCard } from '../api';
import StoryCard from './StoryCard';

export interface StorySlotProps {
  storyId: number;
  /** Toggle button content — the item headline. */
  headline: ReactNode;
  /** Renders between the toggle and the slot — the per-item
   *  ▶ AudioButton, matching the old <li> markup order. */
  trailing?: ReactNode;
}

/**
 * The inline story reader — React port of story.js +
 * _story_card.html: first expand lazily fetches
 * GET /api/news/stories/<id>/, re-click collapses, and the
 * card stays mounted (`hidden`) so re-expanding shows the
 * cached query instantly. The "Arī:" outlet chips refetch
 * with `?source=<slug>` client-side (the stale-slug fallback
 * stays server-side, so chips can't 404).
 */
export default function StorySlot({
  storyId,
  headline,
  trailing,
}: StorySlotProps) {
  const [open, setOpen] = useState(false);
  const [source, setSource] = useState<string | null>(null);
  const slotId = useId();

  const { data, isPending, isError } = useQuery({
    queryKey: ['news', 'story', storyId, source],
    queryFn: () => fetchStoryCard(storyId, source),
    // First expand resolves the card; re-expands serve the
    // cache (the old slot's dataset.loaded behavior).
    enabled: open,
    staleTime: Infinity,
  });

  return (
    <>
      <button
        type="button"
        className="story-toggle"
        data-story={storyId}
        aria-expanded={open}
        aria-controls={slotId}
        onClick={() => setOpen((value) => !value)}
      >
        {headline}
      </button>
      {trailing}
      <div className="story-slot" id={slotId} hidden={!open}>
        {open && isPending && (
          <p className="muted">Ielādē stāstu…</p>
        )}
        {open && isError && (
          <p className="muted" role="alert">
            Neizdevās ielādēt stāstu.
          </p>
        )}
        {data && (
          <StoryCard card={data} onSwitch={setSource} />
        )}
      </div>
    </>
  );
}
