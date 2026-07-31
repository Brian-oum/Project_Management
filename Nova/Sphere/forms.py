from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm

from .models import Client, Project, Profile


def _bootstrapify(fields):
    """Add Bootstrap 5 form-control / form-select / form-check-input classes to every field."""
    for name, field in fields.items():
        widget = field.widget
        if isinstance(widget, (forms.CheckboxInput,)):
            widget.attrs.setdefault('class', 'form-check-input')
        elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
            widget.attrs.setdefault('class', 'form-select')
        else:
            widget.attrs.setdefault('class', 'form-control')


class SphereAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({'placeholder': 'Username'})
        self.fields['password'].widget.attrs.update({'placeholder': 'Password'})
        _bootstrapify(self.fields)


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
        exclude = ['client_id', 'created_at']
        widgets = {
            'physical_address': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrapify(self.fields)


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        exclude = ['created_by', 'created_at', 'updated_at']
        widgets = {
            'project_description': forms.Textarea(attrs={'rows': 3}),
            'business_objectives': forms.Textarea(attrs={'rows': 3}),
            'preferred_completion_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrapify(self.fields)