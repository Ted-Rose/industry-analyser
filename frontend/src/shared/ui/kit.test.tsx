import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AppShell from '../layout/AppShell';
import PageContainer, { PageHeader } from '../layout/PageContainer';
import Badge, { StatusBadge } from './Badge';
import Button from './Button';
import Card, { CardHeader } from './Card';
import Checkbox from './Checkbox';
import DescriptionList from './DescriptionList';
import Disclosure from './Disclosure';
import EmptyState from './EmptyState';
import ErrorState, { Alert } from './ErrorState';
import IconButton from './IconButton';
import Progress from './Progress';
import Prose from './Prose';
import SegmentedControl from './SegmentedControl';
import Skeleton, { LoadingState } from './Skeleton';
import StatCard, { StatGrid } from './StatCard';
import StatusIcon from './StatusIcon';
import Select from './Select';
import { Tabs } from './Tabs';
import ThemeToggle from './ThemeToggle';
import { Check, X } from 'lucide-react';

/**
 * Render-every-variant smoke pass — plan §10's storybook-free
 * self-check: each shared component mounts without throwing and
 * its key affordance lands in the DOM.
 */
describe('shared component kit — smoke', () => {
  it('renders every component variant', () => {
    render(
      <MemoryRouter>
        <AppShell
          appTitle="Kit"
          navItems={[
            { to: '/a', label: 'Tab A', end: true },
            { to: '/b', label: 'Tab B' },
          ]}
        >
          <PageContainer width="narrow">
            <PageHeader
              title="Kit"
              description="All variants"
              back={{ to: '/a', label: 'Back' }}
              actions={<Button size="sm">Act</Button>}
            />
            <Card interactive>
              <CardHeader title="Card" description="Desc" />
            </Card>
            <StatGrid>
              <StatCard label="Runs" value={12} hint="ok" />
            </StatGrid>
            <Badge tone="success" variant="outline" href="/x">
              Tag
            </Badge>
            <StatusBadge status="RUNNING" />
            <Tabs
              tabs={[{ id: 't1', label: 'One' }]}
              active="t1"
              onChange={() => {}}
            />
            <SegmentedControl
              ariaLabel="Pick"
              value="a"
              onChange={() => {}}
              options={[{ value: 'a', label: 'A' }]}
            />
            <EmptyState title="Nothing" />
            <Skeleton className="h-4 w-8" />
            <LoadingState variant="cards" />
            <ErrorState error="boom" onRetry={() => {}} />
            <Alert tone="warning" title="Heads up">
              Careful.
            </Alert>
            <Progress value={3} max={10} label="3/10" />
            <Disclosure summary="More">Body</Disclosure>
            <DescriptionList
              items={[{ term: 'T', description: 'D' }]}
            />
            <Prose html="<p>Hi</p>" />
            <StatusIcon value={true} />
            <Checkbox label="Pick" indeterminate />
            <IconButton icon={<Check />} label="OK" pressed />
            <Button variant="danger" loading leftIcon={<X />}>
              Kill
            </Button>
            <Select defaultValue="b">
              <optgroup label="G">
                <option value="b">Bee</option>
              </optgroup>
            </Select>
            <ThemeToggle />
          </PageContainer>
        </AppShell>
      </MemoryRouter>,
    );

    // Chrome landmarks + representative affordances.
    expect(
      screen.getByRole('link', { name: 'Industry Analyser' }),
    ).toHaveAttribute('href', '/');
    expect(
      screen.getByRole('link', { name: 'Skip to content' }),
    ).toHaveAttribute('href', '#main');
    expect(screen.getAllByRole('main')).not.toHaveLength(0);
    // TopNav renders one ThemeToggle; the page renders another.
    expect(
      screen.getAllByRole('button', { name: 'Theme: auto' })
        .length,
    ).toBe(2);
    expect(
      screen.getByRole('progressbar', { name: '3/10' }),
    ).toHaveAttribute('aria-valuenow', '3');
    expect(
      screen.getByRole('radiogroup', { name: 'Pick' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('tablist'),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('img', { name: 'Yes' }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'OK' }),
    ).toHaveAttribute('aria-pressed', 'true');
    // Native <select> keeps optgroup structure.
    expect(
      screen.getByRole('group', { name: 'G' }),
    ).toBeInTheDocument();
  });
});
