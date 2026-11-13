import type { StoryCardOut } from '../api';

/** 'Y-m-d H:i' — the template's
 *  `{{ article.published_at|date:"Y-m-d H:i" }}`: keep the
 *  stored wall time (ISO prefix), like the old render. */
function formatPublishedAt(iso: string): string {
  return iso.slice(0, 16).replace('T', ' ');
}

export interface StoryCardProps {
  card: StoryCardOut;
  /** Outlet-chip switch — refetches the card with
   *  `?source=<slug>` (stale slugs fall back server-side). */
  onSwitch: (slug: string) => void;
}

/**
 * The _story_card.html fragment as a React component —
 * source name + published_at, title, optional lazy image,
 * lead, "Lasīt oriģinālu" link, <audio> only when audio_url
 * is non-null (else the disabled Klausīties button) and the
 * "Arī:" outlet switcher for the other confirmed members.
 */
export default function StoryCard({ card, onSwitch }: StoryCardProps) {
  const { article } = card;
  return (
    <article className="story-card">
      <p className="muted">
        {article.source_name}
        {article.published_at &&
          ` · ${formatPublishedAt(article.published_at)}`}
      </p>
      <h4>{article.title}</h4>
      {article.image_url && (
        <img src={article.image_url} alt="" loading="lazy" />
      )}
      {article.lead && <p>{article.lead}</p>}
      <p>
        <a href={article.link} rel="noopener">
          Lasīt oriģinālu
        </a>
      </p>
      {card.audio_url ? (
        // eslint-disable-next-line jsx-a11y/media-has-caption
        <audio controls src={card.audio_url} />
      ) : (
        <button type="button" disabled>
          Klausīties
        </button>
      )}
      {card.other_articles.length > 0 && (
        <nav className="story-switcher muted">
          Arī:
          {card.other_articles.map((other) => (
            <button
              key={other.source_slug}
              type="button"
              className="story-switch"
              onClick={() => onSwitch(other.source_slug)}
            >
              {other.source_name}
            </button>
          ))}
        </nav>
      )}
    </article>
  );
}
