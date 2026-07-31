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

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='projects')
    project_name = models.CharField(max_length=150)
    project_description = models.TextField(blank=True)
    project_category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, blank=True)
    business_objectives = models.TextField(blank=True)
    target_users = models.CharField(max_length=150, blank=True)
    expected_number_of_users = models.PositiveIntegerField(null=True, blank=True)
    preferred_completion_date = models.DateField(null=True, blank=True)
    budget_range = models.CharField(max_length=100, blank=True)
    existing_system = models.CharField(max_length=255, blank=True)
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

    def __str__(self):
        return f"{self.project_name} ({self.client.client_name})"