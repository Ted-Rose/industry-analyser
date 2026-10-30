import { useSyncExternalStore } from 'react';
import { Monitor, Moon, Sun } from 'lucide-react';
import {
  cycleTheme,
  getTheme,
  subscribeTheme,
  type Theme,
} from '../theme';
import IconButton from './IconButton';

const ICONS: Record<Theme, typeof Sun> = {
  auto: Monitor,
  light: Sun,
  dark: Moon,
};

/**
 * Cycles auto → light → dark — plan §6 `ui/ThemeToggle`. Writes
 * localStorage['theme'] (the same key Django admin's toggle
 * uses) via theme.ts; a live label keeps the current mode
 * visible to AT ("Theme: auto"). Subscribed via theme.ts's
 * THEME_EVENT + `storage`, so the label/icon stay in sync when
 * the theme changes elsewhere (admin toggle, another tab).
 */
export function ThemeToggle() {
  const theme = useSyncExternalStore(subscribeTheme, getTheme);
  const Icon = ICONS[theme];
  return (
    <IconButton
      icon={<Icon />}
      label={`Theme: ${theme}`}
      onClick={() => cycleTheme()}
    />
  );
}

export default ThemeToggle;
