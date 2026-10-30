import { useState } from 'react';
import { Monitor, Moon, Sun } from 'lucide-react';
import { cycleTheme, getTheme, type Theme } from '../theme';
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
 * visible to AT ("Theme: auto").
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => getTheme());
  const Icon = ICONS[theme];
  return (
    <IconButton
      icon={<Icon />}
      label={`Theme: ${theme}`}
      onClick={() => setTheme(cycleTheme())}
    />
  );
}

export default ThemeToggle;
