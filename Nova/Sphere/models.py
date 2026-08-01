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

    def __str__(self):
        return f"{self.project_name} ({self.client.client_name})"