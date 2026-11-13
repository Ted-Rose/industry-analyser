import { Link } from 'react-router-dom';
import {
  Building,
  CalendarDays,
  ChartColumn,
  House,
  KeyRound,
  Landmark,
  MapPinCheck,
  Scale,
  Tag,
  type LucideIcon,
} from 'lucide-react';
import PageContainer, {
  PageHeader,
} from '../../shared/layout/PageContainer';
import Card from '../../shared/ui/Card';

interface SectionLink {
  to: string;
  label: string;
  icon: LucideIcon;
}

interface Section {
  title: string;
  links: SectionLink[];
}

/** Link labels kept verbatim from the retired index.html. */
const SECTIONS: Section[] = [
  {
    title: 'Apartments',
    links: [
      {
        to: '/apartments/rent',
        label: 'Browse Rental Apartments',
        icon: KeyRound,
      },
      {
        to: '/apartments/sale',
        label: 'Browse Apartments for Sale',
        icon: Tag,
      },
      {
        to: '/apartments/regions/stats',
        label: 'Apartment Regional Statistics',
        icon: ChartColumn,
      },
      {
        to: '/properties/apartments',
        label: 'Apartment Properties (deduplicated)',
        icon: Landmark,
      },
      {
        to: '/apartments/regions/config',
        label: 'Apartment Region Configuration',
        icon: MapPinCheck,
      },
    ],
  },
  {
    title: 'Houses',
    links: [
      {
        to: '/houses/rent',
        label: 'Browse Rental Houses',
        icon: KeyRound,
      },
      {
        to: '/houses/sale',
        label: 'Browse Houses for Sale',
        icon: Tag,
      },
      {
        to: '/houses/regions/stats',
        label: 'House Regional Statistics',
        icon: ChartColumn,
      },
      {
        to: '/properties/houses',
        label: 'House Properties (deduplicated)',
        icon: Landmark,
      },
      {
        to: '/houses/regions/config',
        label: 'House Region Configuration',
        icon: MapPinCheck,
      },
    ],
  },
  {
    title: 'Reports',
    links: [
      {
        to: '/daily-sightings',
        label: 'Daily Sightings Report',
        icon: CalendarDays,
      },
      {
        to: '/rent-vs-buy',
        label: 'Rent vs Buy — months of rent to buy out',
        icon: Scale,
      },
    ],
  },
];

const SECTION_ICONS: Record<string, LucideIcon> = {
  Apartments: Building,
  Houses: House,
  Reports: ChartColumn,
};

/**
 * Static link hub — no API call behind this page. The emoji
 * link-list becomes a card grid of interactive links (plan §9.8).
 */
export default function Index() {
  return (
    <PageContainer width="narrow">
      <PageHeader
        title="Classified Ads"
        description="Real estate listings from SS.com Latvia"
      />

      <div className="space-y-6">
        {SECTIONS.map((section) => {
          const SectionIcon = SECTION_ICONS[section.title];
          return (
            <section key={section.title}>
              <h2
                className="mb-3 flex items-center gap-2 text-xl
                  font-semibold text-fg"
              >
                <SectionIcon
                  className="size-5 text-fg-muted"
                  aria-hidden="true"
                />
                {section.title}
              </h2>
              <div className="grid gap-3 sm:grid-cols-2">
                {section.links.map((link) => (
                  <Card
                    key={link.to}
                    as={Link}
                    to={link.to}
                    interactive
                    className="flex items-center gap-3 no-underline"
                  >
                    <link.icon
                      className="size-5 shrink-0
                        text-fg-muted"
                      aria-hidden="true"
                    />
                    <span className="font-medium text-fg">
                      {link.label}
                    </span>
                  </Card>
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </PageContainer>
  );
}
