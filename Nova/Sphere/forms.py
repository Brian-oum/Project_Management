from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError

from .models import Client, Project, Profile, CostEstimate, Quotation, Invoice, Payment


def _bootstrapify(fields):
    """Add Bootstrap 5 form-control / form-select / form-check-input classes to every field."""
    for name, field in fields.items():
        widget = field.widget
        # NOTE: CheckboxSelectMultiple/RadioSelect are NOT CheckboxInput
        # subclasses. Without this branch they fall into the 'else' below
        # and get class="form-control" — which Bootstrap renders as a
        # full-width, 38px-tall box with no visible check state, on every
        # single checkbox in the list. Must be handled explicitly.
        if isinstance(widget, (forms.CheckboxInput, forms.CheckboxSelectMultiple, forms.RadioSelect)):
            widget.attrs.setdefault('class', 'form-check-input')
        elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
            widget.attrs.setdefault('class', 'form-select')
        else:
            widget.attrs.setdefault('class', 'form-control')


class SphereAuthenticationForm(forms.Form):
    """
    Fully custom login form — email + password, independent of Django's
    default username-based AuthenticationForm. Mimics AuthenticationForm's
    interface (get_user, request kwarg) so it plugs straight into
    django.contrib.auth.views.LoginView.
    """
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'placeholder': 'Email address', 'autofocus': True})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Password'})
    )

    error_messages = {
        'invalid_login': 'Please enter a correct email and password.',
        'inactive': 'This account is inactive.',
    }

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user_cache = None
        super().__init__(*args, **kwargs)
        _bootstrapify(self.fields)

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get('email')
        password = cleaned_data.get('password')

        if email and password:
            self.user_cache = authenticate(self.request, email=email, password=password)
            if self.user_cache is None:
                raise ValidationError(self.error_messages['invalid_login'], code='invalid_login')
            if not self.user_cache.is_active:
                raise ValidationError(self.error_messages['inactive'], code='inactive')
        return cleaned_data

    def get_user(self):
        return self.user_cache


class RegistrationForm(UserCreationForm):
    """Self-service registration for Project Managers only. Admin accounts are
    created separately via `createsuperuser` / the Django admin site."""

    first_name = forms.CharField(max_length=30, required=True)
    last_name = forms.CharField(max_length=30, required=True)
    email = forms.EmailField(required=True)
    phone_number = forms.CharField(max_length=20, required=False)

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrapify(self.fields)

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email already exists.')
        return email

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        if commit:
            user.save()
            Profile.objects.update_or_create(
                user=user,
                defaults={
                    'role': Profile.ROLE_PM,
                    'phone_number': self.cleaned_data.get('phone_number', ''),
                }
            )
        return user


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        exclude = [
            'client_id', 'created_at',
            'has_location', 'physical_address', 'assigned_sales_rep',
        ]
        widgets = {
            'latitude': forms.HiddenInput(),
            'longitude': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrapify(self.fields)
        # Location is fully optional — populated by the map modal, not typed directly
        self.fields['latitude'].required = False
        self.fields['longitude'].required = False
        self.fields['location_address'].required = False

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.has_location = instance.latitude is not None and instance.longitude is not None
        if commit:
            instance.save()
        return instance


class ProjectForm(forms.ModelForm):
    """
    Requirements-gathering form (Phase 2). `expected_number_of_users` and the
    functional-requirement checklists are only meaningful for some project
    categories (see Project.CATEGORY_FIELD_RULES) — the field/group set is
    still rendered for every category so the form works with JS disabled,
    but clean() drops/ignores anything that doesn't apply to the category
    actually chosen, and project_form.html hides those sections visually.

    Business objectives and budget are deliberately not collected here —
    they're settled directly between the PM and the client, not typed
    into this form. The template also presents this as a two-step flow:
    project details first, functional requirements second.
    """

    class Meta:
        model = Project
        exclude = [
            'created_by', 'created_at', 'updated_at',
            'functional_requirements',
        ]
        widgets = {
            'project_description': forms.Textarea(attrs={'rows': 3}),
            'preferred_completion_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # One MultipleChoiceField per feature group, named feature__<group_key>
        # so they're easy to pick out of cleaned_data in save().
        self.feature_group_fields = []
        for group_key, group in Project.FEATURE_GROUPS.items():
            field_name = f'feature__{group_key}'
            self.fields[field_name] = forms.MultipleChoiceField(
                choices=group['choices'],
                widget=forms.CheckboxSelectMultiple,
                required=False,
                label=group['label'],
            )
            self.feature_group_fields.append((group_key, field_name))

        # Expected Number of Users is optional at the DB level already;
        # here we also relax any form-level "required" so categories that
        # don't need it (e.g. Website) never fail validation over it.
        self.fields['expected_number_of_users'].required = False

        # Pre-populate checkboxes. Editing an existing project restores what
        # was actually saved; a brand-new project starts with each group's
        # 'default_selected' choices (e.g. Login/Registration/Password
        # Recovery under User Management) pre-checked as a sensible
        # starting point — the PM can untick anything that doesn't apply.
        if self.instance and self.instance.pk:
            saved_features = self.instance.functional_requirements or {}
            for group_key, field_name in self.feature_group_fields:
                self.initial[field_name] = saved_features.get(group_key, [])
        else:
            for group_key, field_name in self.feature_group_fields:
                default_selected = Project.FEATURE_GROUPS[group_key].get('default_selected')
                if default_selected:
                    self.initial[field_name] = default_selected

        _bootstrapify(self.fields)

    def clean(self):
        cleaned_data = super().clean()
        category = cleaned_data.get('project_category')
        rules = Project.field_rules_for(category)

        # If the chosen category has no countable user base, don't let a
        # stray value (e.g. left over from switching categories) get saved.
        if not rules['has_users']:
            cleaned_data['expected_number_of_users'] = None

        # Same for feature groups that don't apply to this category — a
        # user can't submit "Payment Integration" choices for Networking.
        for group_key, field_name in self.feature_group_fields:
            if group_key not in rules['feature_groups']:
                cleaned_data[field_name] = []

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        functional_requirements = {}
        for group_key, field_name in self.feature_group_fields:
            selected = self.cleaned_data.get(field_name) or []
            if selected:
                functional_requirements[group_key] = selected
        instance.functional_requirements = functional_requirements

        if commit:
            instance.save()
        return instance


class CostEstimateForm(forms.ModelForm):
    """Phase 3 — Project Estimation. Captures the Cost Components that are
    actually relevant to the project's category (see
    Project.CATEGORY_COST_RULES) — e.g. a Networking engagement never sees
    a Domain & Hosting field. Effort-hour breakdowns and staffing plans
    are out of scope. The Functional Requirements Cost is priced
    automatically from Phase 2's selections and isn't a field here — see
    CostEstimate.sync_feature_requirements_cost(), called from the view."""

    class Meta:
        model = CostEstimate
        fields = [field_name for field_name, _label in CostEstimate.COST_FIELDS]
        widgets = {
            field_name: forms.NumberInput(attrs={'step': '0.01', 'min': '0'})
            for field_name, _label in CostEstimate.COST_FIELDS
        }

    def __init__(self, *args, project=None, **kwargs):
        self.project = project
        super().__init__(*args, **kwargs)

        applicable = set(Project.cost_fields_for(project.project_category)) if project \
            else {field_name for field_name, _label in CostEstimate.COST_FIELDS}

        for field_name, label in CostEstimate.COST_FIELDS:
            if field_name not in applicable:
                # Not relevant to this project's category — drop it
                # entirely rather than rendering a field that always has
                # to be zero. The model field itself defaults to 0.00.
                del self.fields[field_name]
                continue
            self.fields[field_name].label = label
            self.fields[field_name].required = False
        _bootstrapify(self.fields)


class TechnicalReviewForm(forms.ModelForm):
    """Phase 4 — Technical Review. Same category-relevant Cost Components as
    Phase 3, editable ('Update Cost Components' / 'Recalculate Cost
    Estimates'), plus Technical Notes. Approval itself is a separate
    explicit action (see views.py), not a field on this form, so it can
    never be set by silently posting the form."""

    class Meta:
        model = CostEstimate
        fields = [field_name for field_name, _label in CostEstimate.COST_FIELDS] + ['technical_notes']
        widgets = {
            **{
                field_name: forms.NumberInput(attrs={'step': '0.01', 'min': '0'})
                for field_name, _label in CostEstimate.COST_FIELDS
            },
            'technical_notes': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # This form is always bound to an existing CostEstimate (instance=
        # estimate), so the project — and its category — comes from there
        # rather than needing to be passed in separately.
        project = self.instance.project if self.instance and self.instance.pk else None
        applicable = set(Project.cost_fields_for(project.project_category)) if project \
            else {field_name for field_name, _label in CostEstimate.COST_FIELDS}

        for field_name, label in CostEstimate.COST_FIELDS:
            if field_name not in applicable:
                del self.fields[field_name]
                continue
            self.fields[field_name].label = label
            self.fields[field_name].required = False
        self.fields['technical_notes'].label = 'Technical Notes'
        self.fields['technical_notes'].required = False
        _bootstrapify(self.fields)


class QuotationForm(forms.ModelForm):
    """Phase 5 — Quotation Generation. Editable terms only: the cost line
    items themselves come straight from the Approved Cost Estimate (Phase
    3/4) and aren't re-entered here. VAT stands in for the generic 'Taxes'
    line from the original workflow doc."""

    class Meta:
        model = Quotation
        fields = ['vat_rate', 'discount_amount', 'payment_terms', 'valid_until']
        widgets = {
            'vat_rate': forms.NumberInput(attrs={'step': '0.01', 'min': '0', 'max': '100'}),
            'discount_amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0'}),
            'payment_terms': forms.Textarea(attrs={'rows': 3, 'placeholder': "e.g. 50% deposit on approval, balance on delivery."}),
            'valid_until': forms.DateInput(attrs={'type': 'date'}),
        }
        labels = {
            'vat_rate': 'VAT Rate (%)',
            'discount_amount': 'Discount',
            'valid_until': 'Quotation Valid Until',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in self.fields:
            self.fields[field_name].required = False
        _bootstrapify(self.fields)


class InvoiceForm(forms.ModelForm):
    """Phase 7 — Invoice Generation. The cost breakdown, Discount and VAT
    come straight from the Approved Quotation and aren't re-entered here.
    The amount collected isn't set here either — it's the sum of the
    invoice's individual Payment records (see PaymentForm below); this
    form only sets the Due Date."""

    class Meta:
        model = Invoice
        fields = ['due_date']
        widgets = {
            'due_date': forms.DateInput(attrs={'type': 'date'}),
        }
        labels = {
            'due_date': 'Due Date',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in self.fields:
            self.fields[field_name].required = False
        _bootstrapify(self.fields)


class PaymentForm(forms.ModelForm):
    """Records one payment against an Invoice — amount, date, method, and
    what it was for (e.g. 'Deposit', 'Milestone 2', 'Final balance'). An
    invoice can have any number of these; Invoice.amount_paid() totals
    them and Invoice.sync_status() re-derives the invoice's status
    whenever one is added or removed (see invoice_view)."""

    class Meta:
        model = Payment
        fields = ['amount', 'date_paid', 'method', 'description']
        widgets = {
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01'}),
            'date_paid': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.TextInput(attrs={
                'placeholder': "What was this for? e.g. Deposit, Milestone 2, Final balance"
            }),
        }
        labels = {
            'date_paid': 'Date Paid',
            'method': 'Payment Method',
            'description': 'What For',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['description'].required = False
        _bootstrapify(self.fields)


class ProjectStatusForm(forms.ModelForm):
    """Lets a PM manually set a project's status directly — to correct a
    mistaken automatic transition, or move it along a step (e.g.
    Lead -> Requirements Gathering) that isn't otherwise driven by a form
    submission elsewhere in the workflow. Intentionally just the one
    field: everything else about the project is edited through its own
    phase-specific form."""

    class Meta:
        model = Project
        fields = ['status']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrapify(self.fields)