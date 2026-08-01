import json
from functools import wraps

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse

from .forms import RegistrationForm, ClientForm, ProjectForm, SphereAuthenticationForm
from .models import Client, Project


def pm_login_required(view_func):
    """
    Custom replacement for django.contrib.auth.decorators.login_required.
    Does NOT depend on settings.LOGIN_URL — always sends unauthenticated
    users to the Sphere login page by its URL name.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('sphere_login')
        return view_func(request, *args, **kwargs)
    return _wrapped


class SphereLoginView(LoginView):
    template_name = 'Sphere/login.html'
    authentication_form = SphereAuthenticationForm
    redirect_authenticated_user = True

    def get_default_redirect_url(self):
        # Hard-coded target instead of relying on settings.LOGIN_REDIRECT_URL
        return reverse('sphere_dashboard')


class SphereLogoutView(LogoutView):
    next_page = 'sphere_login'


def register_view(request):
    """Self-service registration — creates a Project Manager account."""
    if request.user.is_authenticated:
        return redirect('sphere_dashboard')

    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Account created successfully. Welcome to Sphere.')
            return redirect('sphere_dashboard')
    else:
        form = RegistrationForm()
    return render(request, 'Sphere/register.html', {'form': form})


@pm_login_required
def dashboard_view(request):
    context = {
        'total_clients': Client.objects.count(),
        'total_projects': Project.objects.count(),
        'lead_projects': Project.objects.filter(status='LEAD').count(),
        'active_projects': Project.objects.exclude(status__in=['APPROVED', 'REJECTED']).count(),
        'recent_projects': Project.objects.select_related('client')[:5],
        'recent_clients': Client.objects.all()[:5],
    }
    return render(request, 'Sphere/dashboard.html', context)


@pm_login_required
def client_list_view(request):
    clients = Client.objects.all()
    return render(request, 'Sphere/client_list.html', {'clients': clients})


@pm_login_required
def client_create_view(request):
    if request.method == 'POST':
        form = ClientForm(request.POST)
        if form.is_valid():
            client = form.save(commit=False)
            if not client.assigned_sales_rep_id:
                client.assigned_sales_rep = request.user
            client.save()
            messages.success(
                request,
                f'Client "{client.client_name}" registered successfully. '
                f'Now set up their project.'
            )
            return redirect('sphere_project_create_for_client', client_id=client.pk)
    else:
        form = ClientForm(initial={'assigned_sales_rep': request.user})
    return render(request, 'Sphere/client_form.html', {'form': form})


@pm_login_required
def project_list_view(request):
    projects = Project.objects.select_related('client')
    return render(request, 'Sphere/project_list.html', {'projects': projects})


@pm_login_required
def project_create_view(request, client_id=None):
    preselected_client = None
    if client_id:
        preselected_client = get_object_or_404(Client, pk=client_id)

    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save(commit=False)
            project.created_by = request.user
            if not project.project_manager_id:
                project.project_manager = request.user
            project.save()
            messages.success(request, f'Project "{project.project_name}" created successfully.')
            return redirect('sphere_project_list')
    else:
        initial = {'project_manager': request.user}
        if preselected_client:
            initial['client'] = preselected_client
        form = ProjectForm(initial=initial)
    return render(request, 'Sphere/project_form.html', {
        'form': form,
        'preselected_client': preselected_client,
        # Drives the category-aware show/hide JS in project_form.html —
        # which fields/feature groups are relevant for each project category.
        'category_field_rules_json': json.dumps(Project.CATEGORY_FIELD_RULES),
        'default_field_rule_json': json.dumps(Project.DEFAULT_FIELD_RULE),
    })