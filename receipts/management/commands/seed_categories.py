"""Seed per-user receipt spending categories and CategoryRules.

``python manage.py seed_categories --user admin`` creates the
baseline category taxonomy (Latvian grocery vocabulary) plus a
deterministic rule set, then re-runs ``apply_category_rules`` so
existing uncategorized ReceiptItems pick up categories too.

Idempotent: everything goes through ``get_or_create`` — existing
rows (including admin edits to priority/is_active) are never
overwritten, and the apply pass only fills items whose category
is still NULL.

Rule semantics (``receipts.ingest.apply_category_rules``): rules
match ``ReceiptItem.raw_name`` case-insensitively ordered by
(priority, pk); the first matching rule wins. All seeded rules
use ``match_type='contains'`` (substring). Specific patterns that
shadow generic ones — 'biezpiens' contains 'piens' — get a lower
priority number so they win regardless of creation order.
"""

import logging

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from receipts.ingest import _rule_matches, apply_category_rules
from receipts.models import (
    Category,
    CategoryRule,
    Receipt,
    ReceiptItem,
)

logger = logging.getLogger('receipts')

# (category name, [(substring pattern, priority), ...])
# Priority 10 marks specific overrides evaluated before the
# generic priority-50 vocabulary (first matching rule wins).
SEED_CATEGORIES = [
    ('Higiēna', [
        ('zobu ', 50),            # zobu pasta / birste / diegi
        ('šampūn', 50),
        ('ziepe', 50),            # ziepes / ziepe
        ('ziepju', 50),           # cieto ziepju ...
        ('dušas želej', 50),
        ('dezodorant', 50),
        ('tualetes papīr', 50),
        ('tualetpapīr', 50),
        ('salvet', 50),           # salvetes / mitrās salvetes
        ('skuvekļ', 50),          # skuvekļi (razors)
        ('higiēn', 50),           # higiēnas preces
    ]),
    ('Maize', [
        ('maize', 50),            # rudzu maize / rupjmaize ...
        ('maizīt', 50),           # maizītes (buns)
        ('bulciņ', 50),           # bulciņas
        ('kliņģer', 50),          # kliņģeri
        ('bagete', 50),
        ('tortilj', 50),          # tortillas
        ('lavaš', 50),
        ('čabat', 50),            # čabata
    ]),
    ('Olas', [
        ('olas', 50),
        ('olu ', 50),             # olu baltums / vistas olu
    ]),
    ('Piena produkti', [
        # 'biezpiens' contains 'piens' — must be evaluated first.
        ('biezpien', 10),
        ('piens', 50),
        ('piena', 50),            # pilnpiena / piena produkti
        ('krējum', 50),           # saldais krējums
        ('sviest', 50),           # sviests (butter)
        ('sier', 50),             # siers / siera
        ('jogurt', 50),
        ('kefīr', 50),
        ('rjaženka', 50),
        ('margarīn', 50),
        ('panīn', 50),            # panīnas (curd snack)
        ('kārum', 50),            # Kārums brand curd snacks
        ('mocarel', 50),          # mocarella
    ]),
    ('Gaļa', [
        ('desa', 50),             # vārītā / kūpināta desa
        ('cīsiņ', 50),            # cīsiņi (small sausages)
        ('gaļa', 50),             # cūkgaļa / maltā gaļa ...
        ('vist', 50),             # vistas fileja / vista
        ('cūk', 50),              # cūkas fileja ...
        ('liellop', 50),
        ('kotlet', 50),
        ('steik', 50),
        ('bekon', 50),
        ('tītar', 50),            # tītara gaļa
        ('pīl', 50),              # pīle / pīlēns (duck)
    ]),
    ('Sendviču piedevas', [
        ('šķiņķ', 50),            # šķiņķis (ham)
        ('pastēt', 50),           # pastēte
        ('salami', 50),
        ('majonez', 50),
        ('kečup', 50),
        ('sinep', 50),            # sinepes
        ('mērce', 50),            # sauces / condiments
        ('olīvas', 50),           # olives (not 'olīveļļa'!)
        ('olīvu', 50),
        ('sālīti', 50),           # sālīti gurķi (pickles)
        ('pesto', 50),
    ]),
    ('Mājsaimniecība', [
        ('tīrīšan', 50),          # tīrīšanas līdzeklis
        ('mazgājam', 50),         # trauku mazgājamā ...
        ('veļas', 50),            # veļas pulveris / želeja
        ('sūkl', 50),             # sūkļi (sponges)
        ('dvieļ', 50),            # papīra dvieļi
        ('atkritumu', 50),        # atkritumu maisi
        ('maisi', 50),            # maisi / maisiņi (bags)
        ('svec', 50),             # sveces (candles)
        ('baterij', 50),          # baterijas
        ('domestos', 50),
        ('fairy', 50),
    ]),
    ('Preses', [
        ('žurnāl', 50),           # žurnāls / žurnāla
        ('avīz', 50),             # avīze
        ('laikrakst', 50),
        ('sudoku', 50),
    ]),
]


class Command(BaseCommand):
    help = (
        'Seed Category + CategoryRule rows for receipt item '
        'categorization and re-apply rules to uncategorized '
        'ReceiptItems. Idempotent; never overwrites.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            type=str,
            default=None,
            help='Username owning the categories '
                 '(default: first superuser)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print what would change without writing.',
        )

    def _resolve_user(self, username):
        User = get_user_model()
        if username:
            try:
                return User.objects.get(username=username)
            except User.DoesNotExist:
                raise CommandError(f"user '{username}' not found")
        user = (
            User.objects.filter(is_superuser=True)
            .order_by('pk')
            .first()
        )
        if user is None:
            raise CommandError(
                'no superuser exists — pass --user USERNAME'
            )
        return user

    def handle(self, *args, **options):
        user = self._resolve_user(options['user'])
        dry_run = options['dry_run']
        prefix = '[dry-run] ' if dry_run else ''

        cat_created = 0
        rule_created = 0
        for name, patterns in SEED_CATEGORIES:
            category = Category.objects.filter(
                user=user, name=name).first()
            if category is None:
                cat_created += 1
                self.stdout.write(
                    f'category {name}: {prefix}created')
                if not dry_run:
                    category = Category.objects.create(
                        user=user, name=name)
            else:
                self.stdout.write(f'category {name}: unchanged')
            if dry_run:
                # Report rule coverage against the real (or
                # would-be) category without writing.
                existing = set(
                    CategoryRule.objects
                    .filter(
                        user=user, category=category,
                        pattern__in=[p for p, _ in patterns])
                    .values_list('pattern', flat=True)
                ) if category else set()
                rule_created += sum(
                    1 for p, _ in patterns if p not in existing)
                continue
            for pattern, priority in patterns:
                _, created = CategoryRule.objects.get_or_create(
                    user=user,
                    category=category,
                    pattern=pattern,
                    match_type=CategoryRule.CONTAINS,
                    defaults={'priority': priority},
                )
                rule_created += int(created)

        self.stdout.write(
            f'{prefix}{cat_created} category(ies), '
            f'{rule_created} rule(s) created'
        )
        self._apply(user, dry_run, prefix)

    def _apply(self, user, dry_run, prefix):
        """Re-run the real apply_category_rules pass (or simulate
        it in dry-run) over items with a NULL category."""
        items_qs = ReceiptItem.objects.filter(
            receipt__user=user, category__isnull=True)
        if dry_run:
            rules = list(
                CategoryRule.objects
                .filter(user=user, is_active=True)
                .order_by('priority', 'pk'))
            # Include not-yet-created seed rules in the estimate,
            # then re-sort by (priority, creation order) like the
            # real apply pass (priority, pk).
            live = {
                (r.pattern, r.match_type)
                for r in rules
            }
            order = len(rules)
            for name, patterns in SEED_CATEGORIES:
                for pattern, priority in patterns:
                    key = (pattern, CategoryRule.CONTAINS)
                    if key not in live:
                        order += 1
                        rule = CategoryRule(
                            user=user, pattern=pattern,
                            match_type=CategoryRule.CONTAINS,
                            priority=priority)
                        # Simulated insertion order standing in
                        # for the pk tiebreak in the sort below.
                        rule._seed_order = order
                        rules.append(rule)
            rules.sort(key=lambda r: (
                r.priority,
                r.pk if r.pk is not None else r._seed_order))
            matched = sum(
                1 for item in items_qs
                if any(
                    _rule_matches(r, item.raw_name.lower())
                    for r in rules))
            self.stdout.write(
                f'{prefix}{matched}/{items_qs.count()} '
                f'uncategorized item(s) would match'
            )
            return
        for receipt in Receipt.objects.filter(user=user):
            apply_category_rules(user, receipt)
        left = items_qs.count()
        logger.info(
            'seed_categories: user=%s categorized, %d item(s) '
            'still uncategorized', user.username, left)
        self.stdout.write(self.style.SUCCESS(
            f'{prefix}done: {left} item(s) still uncategorized'))
