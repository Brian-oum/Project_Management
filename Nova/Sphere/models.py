from decimal import Decimal

from django.db import models
from django.conf import settings
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


class Profile(models.Model):
    """
    Extends Django's built-in User with the role needed for the IT PMS.
    Admin = full system owner (uses Django's default /admin site).
    Project Manager (PM) = uses the Sphere front-end pages.
    """
    ROLE_ADMIN = 'ADMIN'
    ROLE_PM = 'PM'
    ROLE_CHOICES = [
        (ROLE_ADMIN, 'Admin'),
        (ROLE_PM, 'Project Manager'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default=ROLE_PM)
    phone_number = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.get_role_display()})"


@receiver(post_save, sender=User)
def ensure_profile_exists(sender, instance, created, **kwargs):
    """Safety net: superusers created via createsuperuser also get a Profile (Admin role)."""
    if created:
        Profile.objects.get_or_create(
            user=instance,
            defaults={'role': Profile.ROLE_ADMIN if instance.is_superuser else Profile.ROLE_PM}
        )


class Client(models.Model):
    """Phase 1 — Client Registration."""

    CLIENT_TYPE_CHOICES = [
        ('INDIVIDUAL', 'Individual'),
        ('STARTUP', 'Startup'),
        ('SME', 'SME'),
        ('CORPORATE', 'Corporate'),
        ('GOVERNMENT', 'Government'),
        ('NGO', 'NGO'),
    ]

    client_id = models.CharField(max_length=20, unique=True, blank=True, editable=False)
    client_name = models.CharField(max_length=150)
    company_name = models.CharField(max_length=150, blank=True)
    phone_number = models.CharField(max_length=20)
    email = models.EmailField()
    business_registration_number = models.CharField(max_length=100, blank=True)
    client_type = models.CharField(max_length=20, choices=CLIENT_TYPE_CHOICES, default='INDIVIDUAL')
    industry = models.CharField(max_length=100, blank=True)
    physical_address = models.CharField(max_length=255, blank=True)
    referral_source = models.CharField(max_length=150, blank=True)
    assigned_sales_rep = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assigned_clients'
    )

    # Optional map location — some businesses (e.g. purely online, informal
    # traders) don't have a fixed physical address, so this is opt-in.
    has_location = models.BooleanField(
        default=False,
        help_text='Check this if the business has a physical location to pin on the map.'
    )
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_address = models.CharField(
        max_length=255, blank=True,
        help_text='Human-readable address/landmark for the pinned location (optional).'
    )

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.client_id:
            year = timezone.now().year
            prefix = f"CLI-{year}-"
            last = Client.objects.filter(client_id__startswith=prefix).order_by('-client_id').first()
            next_number = 1
            if last:
                try:
                    next_number = int(last.client_id.replace(prefix, '')) + 1
                except ValueError:
                    next_number = 1
            self.client_id = f"{prefix}{next_number:04d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.client_id} - {self.client_name}"


class Project(models.Model):
    """Phase 1 (project creation) + core of Phase 2 (requirements gathering)."""

    STATUS_CHOICES = [
        ('LEAD', 'Lead'),
        ('REQUIREMENTS_GATHERING', 'Requirements Gathering'),
        ('ANALYSIS', 'Requirements Analysis'),
        ('RECOMMENDATION', 'Solution Recommendation'),
        ('ESTIMATION', 'Project Estimation'),
        ('TECHNICAL_REVIEW', 'Technical Review'),
        ('PROPOSAL_SENT', 'Proposal & Quotation Sent'),
        ('CLIENT_REVIEW', 'Client Review & Approval'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('AWAITING_PAYMENT', 'Awaiting Initial Payment'),
        ('PAID', 'Paid'),
    ]

    CATEGORY_CHOICES = [
        ('WEBSITE', 'Website'),
        ('WEB_APP', 'Web Application'),
        ('MOBILE_APP', 'Mobile Application'),
        ('DESKTOP_APP', 'Desktop Application'),
        ('ERP', 'ERP System'),
        ('CRM', 'CRM'),
        ('POS', 'POS System'),
        ('NETWORKING', 'Networking'),
        ('CYBERSECURITY', 'Cybersecurity'),
        ('CLOUD', 'Cloud Infrastructure'),
        ('AI', 'AI Solution'),
        ('API', 'API Development'),
    ]

    # ------------------------------------------------------------------
    # Category-aware field rules (Phase 2 — Requirements Gathering).
    #
    # Not every field/checklist makes sense for every project type — e.g.
    # a brochure Website has no "expected number of users" to quantify,
    # and Networking/Cybersecurity engagements don't need a Payment
    # Integration checklist. This map drives both form validation
    # (forms.py) and the show/hide behaviour in project_form.html.
    #
    # 'has_users'      -> whether "Expected Number of Users" is relevant
    # 'feature_groups' -> which FEATURE_GROUPS keys apply to this category
    # ------------------------------------------------------------------
    CATEGORY_FIELD_RULES = {
        'WEBSITE': {
            'has_users': False,
            'feature_groups': ['communication', 'reporting', 'integrations', 'hosting'],
        },
        'WEB_APP': {
            'has_users': True,
            'feature_groups': ['user_management', 'payment', 'communication', 'reporting', 'integrations', 'hosting'],
        },
        'MOBILE_APP': {
            'has_users': True,
            'feature_groups': ['user_management', 'payment', 'communication', 'reporting', 'integrations'],
        },
        'DESKTOP_APP': {
            'has_users': True,
            'feature_groups': ['user_management', 'reporting', 'integrations'],
        },
        'ERP': {
            'has_users': True,
            'feature_groups': ['user_management', 'payment', 'communication', 'reporting', 'integrations', 'hosting'],
        },
        'CRM': {
            'has_users': True,
            'feature_groups': ['user_management', 'communication', 'reporting', 'integrations', 'hosting'],
        },
        'POS': {
            'has_users': True,
            'feature_groups': ['user_management', 'payment', 'reporting', 'integrations'],
        },
        'NETWORKING': {
            'has_users': False,
            'feature_groups': ['integrations', 'hosting'],
        },
        'CYBERSECURITY': {
            'has_users': False,
            'feature_groups': ['integrations', 'reporting'],
        },
        'CLOUD': {
            'has_users': False,
            'feature_groups': ['integrations', 'hosting', 'reporting'],
        },
        'AI': {
            'has_users': True,
            'feature_groups': ['user_management', 'reporting', 'integrations', 'hosting'],
        },
        'API': {
            'has_users': False,
            'feature_groups': ['integrations', 'hosting', 'reporting'],
        },
    }

    # Default rule used when a category has no entry above, or none is
    # selected yet (e.g. a brand-new, unsaved form) — err on the side of
    # showing everything rather than hiding something the user needs.
    DEFAULT_FIELD_RULE = {
        'has_users': True,
        'feature_groups': ['user_management', 'payment', 'communication', 'reporting', 'integrations', 'hosting'],
    }

    # Functional requirements checklist, grouped the same way as the
    # requirements-gathering phase. Keys are stored in `functional_requirements`.
    FEATURE_GROUPS = {
        'user_management': {
            'label': 'User Management',
            'choices': [
                ('login', 'Login'),
                ('registration', 'Registration'),
                ('password_recovery', 'Password Recovery'),
                ('rbac', 'Role-Based Access Control'),
                ('user_profiles', 'User Profiles'),
            ],
            # Core auth basics that almost every system needs — pre-checked
            # on new projects so the PM doesn't have to tick them manually,
            # but they remain ordinary checkboxes and can be unchecked.
            'default_selected': ['login', 'registration', 'password_recovery'],
        },
        'payment': {
            'label': 'Payment Integration',
            'choices': [
                ('mpesa_stk', 'M-Pesa STK Push'),
                ('card', 'Card Payment'),
            ],
        },
        'communication': {
            'label': 'Communication',
            'choices': [
                ('email', 'Email Notifications'),
                ('sms', 'SMS Notifications'),
                ('push', 'Push Notifications'),
                ('whatsapp', 'WhatsApp Integration'),
                ('live_chat', 'Live Chat'),
            ],
        },
        'reporting': {
            'label': 'Reporting',
            'choices': [
                ('dashboard', 'Dashboard'),
                ('analytics', 'Analytics'),
                ('charts', 'Charts'),
                ('pdf_reports', 'PDF Reports'),
                ('excel_export', 'Excel Export'),
            ],
        },
        'integrations': {
            'label': 'Third-Party Integrations',
            'choices': [
                ('google_maps', 'Google Maps'),
                ('google_analytics', 'Google Analytics'),
                ('ms365', 'Microsoft 365'),
                ('quickbooks', 'QuickBooks'),
                ('firebase', 'Firebase'),
                ('openai', 'OpenAI API'),
                ('twilio', 'Twilio'),
                ('daraja', 'Daraja API'),
            ],
        },
        'hosting': {
            'label': 'Hosting Requirements',
            'choices': [
                ('shared', 'Shared Hosting'),
                ('vps', 'VPS'),
                ('dedicated', 'Dedicated Server'),
                ('aws', 'AWS'),
                ('azure', 'Azure'),
                ('digitalocean', 'DigitalOcean'),
                ('cloudflare', 'Cloudflare CDN'),
            ],
        },
    }

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='projects')
    project_name = models.CharField(max_length=150)
    project_description = models.TextField(blank=True)
    project_category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, blank=True)
    target_users = models.CharField(max_length=150, blank=True)
    expected_number_of_users = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='Only relevant for categories with a countable user base (see CATEGORY_FIELD_RULES).'
    )
    preferred_completion_date = models.DateField(null=True, blank=True)
    existing_system = models.CharField(max_length=255, blank=True)

    # Phase 2 — Functional Requirements, captured as {group_key: [choice_key, ...]}.
    # Only groups relevant to the chosen project_category are ever shown
    # or saved from the form (see ProjectForm), but the field itself
    # stays generic so future categories/groups don't need a migration.
    functional_requirements = models.JSONField(default=dict, blank=True)

    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default='LEAD')
    project_manager = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='managed_projects'
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='created_projects'
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    @classmethod
    def field_rules_for(cls, category):
        """Return the CATEGORY_FIELD_RULES entry for a category, falling back
        to DEFAULT_FIELD_RULE if the category is blank/unrecognised."""
        return cls.CATEGORY_FIELD_RULES.get(category, cls.DEFAULT_FIELD_RULE)

    def needs_user_count(self):
        """Whether 'Expected Number of Users' is meaningful for this project."""
        return self.field_rules_for(self.project_category)['has_users']

    def applicable_feature_groups(self):
        """Feature-group keys relevant to this project's category."""
        return self.field_rules_for(self.project_category)['feature_groups']

    # ------------------------------------------------------------------
    # Functional Requirements pricing.
    #
    # Functional requirements are costed on their own and kept separate
    # from the Total Development Cost cost component (see CostEstimate) —
    # a project's price isn't just "development time", it's development
    # plus every feature the client asked for in Phase 2. Keyed the same
    # way as FEATURE_GROUPS/functional_requirements: {group_key: {choice_key: cost}}.
    # A missing entry prices at KES 0 rather than raising, so adding a new
    # choice to FEATURE_GROUPS without pricing it yet doesn't break costing.
    #
    # NOTE: 'user_management' and 'reporting' are deliberately absent —
    # those two groups are treated as baseline functionality already
    # covered by Total Development Cost, not billed again on top of it.
    # See DEVELOPMENT_INCLUDED_FEATURE_GROUPS below.
    # ------------------------------------------------------------------
    FEATURE_COSTS = {
        'payment': {
            'mpesa_stk': Decimal('30000'),
            'card': Decimal('35000'),
        },
        'communication': {
            'email': Decimal('8000'),
            'sms': Decimal('15000'),
            'push': Decimal('18000'),
            'whatsapp': Decimal('25000'),
            'live_chat': Decimal('30000'),
        },
        'integrations': {
            'google_maps': Decimal('12000'),
            'google_analytics': Decimal('8000'),
            'ms365': Decimal('20000'),
            'quickbooks': Decimal('25000'),
            'firebase': Decimal('18000'),
            'openai': Decimal('30000'),
            'twilio': Decimal('20000'),
            'daraja': Decimal('20000'),
        },
        'hosting': {
            'shared': Decimal('5000'),
            'vps': Decimal('15000'),
            'dedicated': Decimal('40000'),
            'aws': Decimal('20000'),
            'azure': Decimal('20000'),
            'digitalocean': Decimal('15000'),
            'cloudflare': Decimal('8000'),
        },
    }

    # Feature groups whose cost is already folded into Total Development
    # Cost rather than priced separately in the Functional Requirements
    # Cost. User Management (login/registration/etc.) and Reporting are
    # treated as baseline build work for any project, not add-on features.
    DEVELOPMENT_INCLUDED_FEATURE_GROUPS = {'user_management', 'reporting'}

    # ------------------------------------------------------------------
    # Category-aware cost components (Phase 3 — Project Estimation).
    #
    # Mirrors CATEGORY_FIELD_RULES: not every Cost Component applies to
    # every project type — e.g. a Desktop Application has no ongoing API
    # subscription. Drives which fields CostEstimateForm /
    # TechnicalReviewForm actually expose for a given project.
    # ------------------------------------------------------------------
    CATEGORY_COST_RULES = {
        'WEBSITE': ['development_cost'],
        'WEB_APP': ['development_cost', 'api_subscription_cost'],
        'MOBILE_APP': ['development_cost', 'api_subscription_cost'],
        'DESKTOP_APP': ['development_cost'],
        'ERP': ['development_cost', 'api_subscription_cost'],
        'CRM': ['development_cost', 'api_subscription_cost'],
        'POS': ['development_cost', 'api_subscription_cost'],
        'NETWORKING': ['development_cost'],
        'CYBERSECURITY': ['development_cost', 'api_subscription_cost'],
        'CLOUD': ['development_cost', 'api_subscription_cost'],
        'AI': ['development_cost', 'api_subscription_cost'],
        'API': ['development_cost', 'api_subscription_cost'],
    }

    # Fallback when a category has no entry above (or none is selected
    # yet) — err on the side of showing every Cost Component rather than
    # hiding one a PM actually needs to fill in.
    DEFAULT_COST_RULE = ['development_cost', 'api_subscription_cost']

    @classmethod
    def cost_fields_for(cls, category):
        """Cost Component field names relevant to a category, falling back
        to DEFAULT_COST_RULE if the category is blank/unrecognised."""
        return cls.CATEGORY_COST_RULES.get(category, cls.DEFAULT_COST_RULE)

    def functional_requirements_display(self):
        """Human-readable {group label: [choice labels]} for saved selections,
        used in templates/admin without re-deriving choice labels there."""
        display = {}
        for group_key, selected_keys in (self.functional_requirements or {}).items():
            group = self.FEATURE_GROUPS.get(group_key)
            if not group or not selected_keys:
                continue
            choice_labels = dict(group['choices'])
            display[group['label']] = [choice_labels.get(k, k) for k in selected_keys]
        return display

    def development_included_requirements_display(self):
        """Human-readable {group label: [choice labels]} for just the
        groups in DEVELOPMENT_INCLUDED_FEATURE_GROUPS (User Management,
        Reporting) — shown separately so their selections stay visible
        even though they aren't priced as part of the Functional
        Requirements Cost."""
        display = {}
        for group_key, selected_keys in (self.functional_requirements or {}).items():
            if group_key not in self.DEVELOPMENT_INCLUDED_FEATURE_GROUPS:
                continue
            group = self.FEATURE_GROUPS.get(group_key)
            if not group or not selected_keys:
                continue
            choice_labels = dict(group['choices'])
            display[group['label']] = [choice_labels.get(k, k) for k in selected_keys]
        return display

    def functional_requirements_cost_breakdown(self):
        """[(group label, [(choice label, cost), ...]), ...] for saved
        selections — the priced counterpart to functional_requirements_display(),
        used to show and total the Functional Requirements Cost in Phase 3/4.
        Skips DEVELOPMENT_INCLUDED_FEATURE_GROUPS, since those are already
        covered by Total Development Cost."""
        breakdown = []
        for group_key, selected_keys in (self.functional_requirements or {}).items():
            if group_key in self.DEVELOPMENT_INCLUDED_FEATURE_GROUPS:
                continue
            group = self.FEATURE_GROUPS.get(group_key)
            if not group or not selected_keys:
                continue
            choice_labels = dict(group['choices'])
            costs = self.FEATURE_COSTS.get(group_key, {})
            items = [(choice_labels.get(k, k), costs.get(k, Decimal('0.00'))) for k in selected_keys]
            breakdown.append((group['label'], items))
        return breakdown

    def functional_requirements_cost(self):
        """Total price of every selected functional requirement outside
        DEVELOPMENT_INCLUDED_FEATURE_GROUPS, summed across all groups.
        Deliberately its own figure — kept independent of Total
        Development Cost — since these features are priced per feature,
        not folded into the lump development estimate."""
        total = Decimal('0.00')
        for _group_label, items in self.functional_requirements_cost_breakdown():
            for _choice_label, cost in items:
                total += cost
        return total

    def has_requirements(self):
        """Whether Phase 2 (Requirements Gathering) has actually been filled
        in yet — used to gate the on-demand SRS/Feature List/Scope outputs
        so they're not generated from an empty project."""
        return bool(self.project_category) or bool(self.functional_requirements)

    def srs_reference(self):
        """Stable, human-readable reference code for the generated SRS,
        e.g. SRS-CLI-2026-0001-P0007."""
        if not self.pk:
            return None
        return f"SRS-{self.client.client_id}-P{self.pk:04d}"

    def initial_project_scope(self):
        """
        Auto-generated one-paragraph scope statement, compiled from whatever
        was captured during Phase 2 — this is the 'Initial Project Scope'
        output referenced in the workflow documentation. Deliberately plain
        prose (not a template dump) so it reads naturally regardless of
        which fields happen to be filled in.
        """
        if not self.has_requirements():
            return ''

        category_label = self.get_project_category_display() if self.project_category else 'a to-be-defined category'
        sentences = [
            f"{self.project_name} is a {category_label.lower()} engagement for {self.client.client_name}."
        ]

        if self.project_description:
            sentences.append(self.project_description.strip())

        if self.target_users:
            sentences.append(f"The primary target users are {self.target_users}.")

        if self.needs_user_count() and self.expected_number_of_users:
            sentences.append(
                f"The system should be designed to support approximately "
                f"{self.expected_number_of_users} users."
            )

        if self.existing_system:
            sentences.append(
                f"This project replaces or integrates with the client's existing system: {self.existing_system}."
            )

        if self.preferred_completion_date:
            sentences.append(
                f"The client's preferred completion date is {self.preferred_completion_date:%B %d, %Y}."
            )

        return ' '.join(sentences)

    def __str__(self):
        return f"{self.project_name} ({self.client.client_name})"

    def has_cost_estimate(self):
        """Whether Phase 3 (Project Estimation) has been started for this project."""
        return hasattr(self, 'cost_estimate')

    def has_quotation(self):
        """Whether Phase 5 (Quotation Generation) has been started for this project."""
        return hasattr(self, 'quotation')

    def has_invoice(self):
        """Whether Phase 7 (Invoice Generation) has been started for this project."""
        return self.has_quotation() and hasattr(self.quotation, 'invoice')


class CostEstimate(models.Model):
    """
    Phase 3 — Project Estimation (Cost Components) + Phase 4 — Technical
    Review, combined into a single record. There is one estimate per
    project: Phase 3 creates it (status Draft), Phase 4 lets any PM adjust
    the cost components, add technical notes, recalculate, and approve it
    (status Approved). Effort-hour breakdowns and staffing plans are
    deliberately out of scope, per the quotation-focused workflow.

    Editing an already-Approved estimate's cost components (i.e.
    "Recalculate Cost Estimates" after the fact) reopens it — status drops
    back to Draft and the previous approval is cleared, since the approved
    total no longer matches what's on record. See technical_review_view.
    """

    STATUS_DRAFT = 'DRAFT'
    STATUS_APPROVED = 'APPROVED'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_APPROVED, 'Approved'),
    ]

    # (field_name, label) — the Cost Components a PM fills in directly.
    # Infrastructure Cost and Domain & Hosting Cost have been removed as
    # separate line items: hosting-related costs are now captured through
    # the Hosting Requirements functional-requirement group instead (see
    # Project.FEATURE_COSTS['hosting']), priced per project rather than as
    # a flat estimate field. The Functional Requirements Cost is
    # deliberately NOT in this list — it's priced automatically from
    # Phase 2's selections (see Project.functional_requirements_cost) and
    # kept independent of these, rather than typed in here.
    # Iterated by forms/templates/admin instead of hard-coding each field
    # name in several different places.
    COST_FIELDS = [
        ('development_cost', 'Total Development Cost'),
        ('api_subscription_cost', 'API Subscription Costs'),
    ]

    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name='cost_estimate')

    development_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'),
        help_text='Covers core build work, including baseline User Management and Reporting features.'
    )
    api_subscription_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    # Auto-calculated from the project's Functional Requirements (Phase 2)
    # via sync_feature_requirements_cost() — not directly editable through
    # CostEstimateForm/TechnicalReviewForm, since it isn't a number a PM
    # types in, it's a sum of per-feature prices. Kept independent of, and
    # added on top of, the Cost Components above. User Management and
    # Reporting selections are excluded from this figure — they're
    # covered by development_cost instead (see
    # Project.DEVELOPMENT_INCLUDED_FEATURE_GROUPS).
    feature_requirements_cost = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'), editable=False,
        help_text='Auto-calculated from the Functional Requirements selected in Phase 2, excluding '
                   'User Management and Reporting (already covered by Total Development Cost).'
    )

    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    technical_notes = models.TextField(
        blank=True,
        help_text="Technical Review notes — visible to the team, not sent to the client."
    )

    prepared_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='prepared_estimates',
        help_text='PM who created the initial Phase 3 estimate.'
    )
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_estimates',
        help_text='PM who most recently approved this estimate (Phase 4).'
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def applicable_cost_fields(self):
        """[(field_name, label), ...] restricted to the Cost Components
        relevant to this project's category (see Project.CATEGORY_COST_RULES)
        — mirrors Project.applicable_feature_groups()."""
        applicable = set(Project.cost_fields_for(self.project.project_category))
        return [(field_name, label) for field_name, label in self.COST_FIELDS if field_name in applicable]

    def sync_feature_requirements_cost(self):
        """Recompute feature_requirements_cost from the project's saved
        Functional Requirements. Functional Requirements themselves aren't
        edited from Phase 3/4, so this is called whenever the estimate is
        created or its Cost Components are recalculated, to keep the two
        in step without letting a PM type the figure in by hand."""
        self.feature_requirements_cost = self.project.functional_requirements_cost()
        return self.feature_requirements_cost

    def total_cost(self):
        """Grand total: the Cost Components plus the Functional
        Requirements Cost — the 'Project Cost Estimate' output."""
        component_total = sum((getattr(self, field_name) for field_name, _ in self.COST_FIELDS), Decimal('0.00'))
        return component_total + self.feature_requirements_cost

    def cost_breakdown(self):
        """[(label, amount), ...] in a fixed, doc-matching order — for
        templates/admin. Includes the Functional Requirements Cost as its
        own line, kept separate from the Cost Components proper."""
        return [(label, getattr(self, field_name)) for field_name, label in self.COST_FIELDS] + [
            ('Functional Requirements Cost', self.feature_requirements_cost),
        ]

    def is_approved(self):
        return self.status == self.STATUS_APPROVED

    def approve(self, user):
        """Technical Review action: approve the current cost estimate as-is."""
        self.status = self.STATUS_APPROVED
        self.reviewed_by = user
        self.approved_at = timezone.now()
        self.save()

    def reopen(self):
        """Drop back to Draft — used when an Approved estimate's numbers are
        recalculated, since the prior approval no longer matches the total."""
        self.status = self.STATUS_DRAFT
        self.reviewed_by = None
        self.approved_at = None

    def __str__(self):
        return f"Estimate for {self.project.project_name} — {self.get_status_display()} (KES {self.total_cost():,.2f})"


class Quotation(models.Model):
    """
    Phase 5 — Quotation Generation, combined with Phase 6 — Client Review
    & Approval (the quotation IS the thing being reviewed, so its status
    field carries both). Generated from an Approved Cost Estimate only:
    the estimate's Cost Components and Functional Requirements Cost pass
    through unchanged as the Subtotal, then a Discount and VAT are applied
    to produce the Grand Total. No separate technical proposal document is
    produced, and Taxes are represented specifically as VAT rather than a
    generic tax line, per Kenyan practice.

    There's no separate client-facing portal in this system, so the
    client's decision (Accept / Request Revisions / Reject) is recorded by
    a PM on the client's behalf via record_client_decision() — see
    quotation_view in views.py.
    """

    STATUS_DRAFT = 'DRAFT'
    STATUS_SENT = 'SENT'
    STATUS_UNDER_REVIEW = 'UNDER_REVIEW'
    STATUS_APPROVED = 'APPROVED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_REVISION_REQUESTED = 'REVISION_REQUESTED'
    STATUS_EXPIRED = 'EXPIRED'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SENT, 'Sent'),
        (STATUS_UNDER_REVIEW, 'Under Review'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_REVISION_REQUESTED, 'Revision Requested'),
        (STATUS_EXPIRED, 'Expired'),
    ]

    # Kenya's standard VAT rate — used as the default for every new
    # quotation, but editable per-quotation in case a project is
    # zero-rated/exempt or the rate changes.
    DEFAULT_VAT_RATE = Decimal('16.00')

    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name='quotation')
    quotation_number = models.CharField(max_length=20, unique=True, blank=True, editable=False)

    vat_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=DEFAULT_VAT_RATE,
        help_text='VAT percentage applied to the subtotal after any discount (default 16%).'
    )
    discount_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'), blank=True,
        help_text='Flat discount applied to the subtotal before VAT, if any.'
    )

    payment_terms = models.TextField(
        blank=True,
        help_text="e.g. '50% deposit on approval, balance due on delivery.'"
    )
    valid_until = models.DateField(
        null=True, blank=True,
        help_text='Quotation Validity Period — the date this quotation expires.'
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    client_notes = models.TextField(
        blank=True,
        help_text="Client's reason for a rejection or revision request, if given."
    )

    generated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='generated_quotations',
        help_text='PM who generated the quotation.'
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True, help_text='When the client decision was recorded.')

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.quotation_number:
            year = timezone.now().year
            prefix = f"QUO-{year}-"
            last = Quotation.objects.filter(quotation_number__startswith=prefix).order_by('-quotation_number').first()
            next_number = 1
            if last:
                try:
                    next_number = int(last.quotation_number.replace(prefix, '')) + 1
                except ValueError:
                    next_number = 1
            self.quotation_number = f"{prefix}{next_number:04d}"
        super().save(*args, **kwargs)

    def cost_component_items(self):
        """[(label, amount), ...] — the Cost Estimate's directly-entered
        Cost Components only (Total Development Cost, API Subscription
        Costs, etc.). Deliberately excludes Functional Requirements Cost —
        see feature_requirement_groups() for that breakdown, which is
        shown as its own section rather than folded into this list."""
        estimate = self.project.cost_estimate
        return [(label, getattr(estimate, field_name)) for field_name, label in estimate.COST_FIELDS]

    def feature_requirement_groups(self):
        """[(group_label, [(feature_label, cost), ...]), ...] — the
        per-feature breakdown behind the Functional Requirements Cost,
        straight from Project.functional_requirements_cost_breakdown().
        Lets the quotation show the client exactly which selected
        features make up that figure, instead of a single lump sum."""
        return self.project.functional_requirements_cost_breakdown()

    def feature_requirements_total(self):
        """The Functional Requirements Cost total — same figure as
        CostEstimate.feature_requirements_cost, exposed here so templates
        don't need to reach through project.cost_estimate directly."""
        return self.project.cost_estimate.feature_requirements_cost

    def line_items(self):
        """[(label, amount), ...] pulled straight from the project's
        Approved Cost Estimate — these make up the Subtotal below. Flat
        view kept for places a simple list is enough (e.g. the sidebar
        snapshot); the printable quotation itself uses
        cost_component_items() + feature_requirement_groups() instead so
        it can show the Functional Requirements breakdown."""
        return self.project.cost_estimate.cost_breakdown()

    def subtotal(self):
        """Sum of the Cost Estimate's line items — before Discount and VAT."""
        return self.project.cost_estimate.total_cost()

    def taxable_amount(self):
        """Subtotal net of the Discount — what VAT is actually charged on."""
        taxable = self.subtotal() - self.discount_amount
        return taxable if taxable > Decimal('0.00') else Decimal('0.00')

    def vat_amount(self):
        """VAT — replaces the generic 'Taxes' line from the original
        workflow doc, computed at vat_rate% of the discounted subtotal."""
        return (self.taxable_amount() * self.vat_rate / Decimal('100')).quantize(Decimal('0.01'))

    def grand_total(self):
        """Subtotal, less Discount, plus VAT — the amount the client owes."""
        return self.taxable_amount() + self.vat_amount()

    def is_approved(self):
        return self.status == self.STATUS_APPROVED

    def is_editable(self):
        """Terms (VAT rate, discount, payment terms, validity) can still be
        changed — false once the client has made a final decision, so an
        Approved/Rejected quotation isn't quietly altered after the fact."""
        return self.status not in (self.STATUS_APPROVED, self.STATUS_REJECTED)

    def mark_sent(self):
        """Phase 5 -> Phase 6 handoff: the quotation has gone out to the client."""
        self.status = self.STATUS_SENT
        self.sent_at = timezone.now()
        self.save()

    def revise(self):
        """Reopen a Rejected quotation for another round, after the PM has
        gone back and adjusted the Cost Estimate and/or Functional
        Requirements. Deliberately doesn't touch project.cost_estimate —
        cost_component_items(), feature_requirement_groups(), subtotal()
        etc. all read the estimate live, so whatever the PM has already
        approved there shows up here automatically.

        Issues a new quotation_number rather than quietly editing the
        rejected one in place — this is a new document as far as the
        client is concerned, not a silent revision of the one they
        already turned down. VAT rate / discount / payment terms /
        validity are left as they were rather than reset, since those are
        usually still correct and the PM can adjust them same as normal.
        """
        if self.status != self.STATUS_REJECTED:
            raise ValueError('Only a rejected quotation can be revised.')
        self.status = self.STATUS_DRAFT
        self.client_notes = ''
        self.decided_at = None
        self.sent_at = None
        self.quotation_number = ''  # save() below will assign the next number
        self.save()

    def record_client_decision(self, status, notes=''):
        """Phase 6 — Accept / Request Revisions / Reject, recorded by a PM
        on the client's behalf since there's no separate client portal."""
        self.status = status
        self.client_notes = notes
        self.decided_at = timezone.now()
        self.save()

    def __str__(self):
        return f"{self.quotation_number} — {self.project.project_name} ({self.get_status_display()})"


class Invoice(models.Model):
    """
    Phase 7 — Invoice Generation. Converts a client-Approved Quotation
    (Phase 6) into an invoice without re-entering project information —
    the cost breakdown, Discount and VAT all pass through unchanged from
    the Quotation (see total_due()/outstanding_balance() below), same
    approach as Quotation reading live off the Approved Cost Estimate.
    No contract is drafted by this system, and Payment Milestones are
    represented by the Quotation's existing Payment Terms text rather
    than a separate structured schedule.

    There's no separate client-facing portal, so — same as
    Quotation.record_client_decision() — the PM records what's actually
    been collected (Amount Already Paid) on the client's behalf; status
    is then derived automatically rather than picked by hand, so it can
    never drift out of step with the numbers.
    """

    STATUS_AWAITING_PAYMENT = 'AWAITING_PAYMENT'
    STATUS_PARTIALLY_PAID = 'PARTIALLY_PAID'
    STATUS_PAID = 'PAID'
    STATUS_CHOICES = [
        (STATUS_AWAITING_PAYMENT, 'Awaiting Initial Payment'),
        (STATUS_PARTIALLY_PAID, 'Partially Paid'),
        (STATUS_PAID, 'Paid'),
    ]

    quotation = models.OneToOneField(Quotation, on_delete=models.CASCADE, related_name='invoice')
    invoice_number = models.CharField(max_length=20, unique=True, blank=True, editable=False)

    invoice_date = models.DateField(default=timezone.now)
    due_date = models.DateField(
        null=True, blank=True,
        help_text='When payment is due. Defaults blank — set explicitly per invoice.'
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_AWAITING_PAYMENT)

    generated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='generated_invoices',
        help_text='PM who generated the invoice.'
    )

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def project(self):
        """Convenience passthrough — mirrors how Quotation reaches Project
        via project.quotation, just in the other direction."""
        return self.quotation.project

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            year = timezone.now().year
            prefix = f"INV-{year}-"
            last = Invoice.objects.filter(invoice_number__startswith=prefix).order_by('-invoice_number').first()
            next_number = 1
            if last:
                try:
                    next_number = int(last.invoice_number.replace(prefix, '')) + 1
                except ValueError:
                    next_number = 1
            self.invoice_number = f"{prefix}{next_number:04d}"
        super().save(*args, **kwargs)

    def total_due(self):
        """The invoice total — the Quotation's Grand Total, read live so it
        can never drift from what the client actually agreed to pay."""
        return self.quotation.grand_total()

    def amount_paid(self):
        """Sum of every recorded Payment against this invoice. Payments are
        tracked individually (see Payment below) rather than as a single
        running figure, so there's a visible history of what was paid,
        when, and what for."""
        return self.payments.aggregate(total=models.Sum('amount'))['total'] or Decimal('0.00')

    def outstanding_balance(self):
        """Total Due less the sum of recorded Payments, floored at KES 0."""
        balance = self.total_due() - self.amount_paid()
        return balance if balance > Decimal('0.00') else Decimal('0.00')

    def sync_status(self):
        """Derive status from recorded Payments vs total_due, so it's never
        set by hand and can't fall out of step with the actual numbers.
        Called from invoice_view whenever a Payment is added or removed."""
        paid = self.amount_paid()
        if paid <= Decimal('0.00'):
            self.status = self.STATUS_AWAITING_PAYMENT
        elif self.outstanding_balance() <= Decimal('0.00'):
            self.status = self.STATUS_PAID
        else:
            self.status = self.STATUS_PARTIALLY_PAID
        return self.status

    def is_paid(self):
        return self.status == self.STATUS_PAID

    def __str__(self):
        return f"{self.invoice_number} — {self.project.project_name} ({self.get_status_display()})"


class Payment(models.Model):
    """
    Individual payments recorded against an Invoice (Phase 7). An invoice
    is often settled in more than one instalment — a deposit, a milestone
    payment, a final balance — each collected on a different date, by a
    different method, and for a different reason. Recording them one at a
    time (rather than a single running "amount paid" figure) keeps that
    history visible on the invoice and lets Invoice.amount_paid() total
    them up live, same as Invoice reads its own total_due() live off the
    Quotation.
    """

    METHOD_MPESA = 'MPESA'
    METHOD_BANK_TRANSFER = 'BANK_TRANSFER'
    METHOD_PAYPAL = 'PAYPAL'
    METHOD_STRIPE = 'STRIPE'
    METHOD_OTHER = 'OTHER'
    METHOD_CHOICES = [
        (METHOD_MPESA, 'M-Pesa'),
        (METHOD_BANK_TRANSFER, 'Bank Transfer'),
        (METHOD_PAYPAL, 'PayPal'),
        (METHOD_STRIPE, 'Stripe'),
        (METHOD_OTHER, 'Other'),
    ]

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date_paid = models.DateField(default=timezone.now)
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default=METHOD_MPESA)
    description = models.CharField(
        max_length=255, blank=True,
        help_text="What this payment was for, e.g. 'Deposit', 'Milestone 2 — design sign-off', 'Final balance'."
    )

    recorded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='recorded_payments',
        help_text='PM who recorded the payment.'
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-date_paid', '-created_at']

    def __str__(self):
        return f"KES {self.amount:,.2f} on {self.date_paid} — {self.invoice.invoice_number}"