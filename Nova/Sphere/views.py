import json
import os
from decimal import Decimal
from functools import wraps

from io import BytesIO

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.staticfiles import finders
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse, NoReverseMatch
from django.utils import timezone
from xhtml2pdf import pisa

from .forms import (
    RegistrationForm, ClientForm, ProjectForm, SphereAuthenticationForm,
    CostEstimateForm, TechnicalReviewForm, QuotationForm, InvoiceForm,
    PaymentForm, ProjectStatusForm, ProjectCompletionForm,
)
from .models import Client, Project, CostEstimate, Quotation, Invoice, Payment


# Letterhead details for the invoice document (on-screen and PDF). Edit these
# to match your actual business — or replace with a lookup against a Company/
# Settings model if you'd rather manage this from the admin than from code.
SPHERE_COMPANY_PROFILE = {
    'address': 'Nairobi, Kenya',
    'phone': '+254 714 937 625',
    'email': ' info@novasphereitsolutions.co.ke',
    'payment_till': '6954022',
}


def pdf_link_callback(uri, rel):
    """
    xhtml2pdf (pisa) renders in-process — it has no web server in front of
    it, so it can't fetch '/static/...' or '/media/...' URLs the way a
    browser would. Every such URI (e.g. the logo <img src="{% static %}">
    in invoice_pdf.html / quotation_pdf.html) has to be translated into an
    absolute filesystem path before pisa can embed it. Without this, pisa
    just silently drops the image and renders the rest of the page fine —
    which is exactly the "logo missing from the PDF, but fine on screen"
    symptom.

    This is passed as link_callback= to pisa.CreatePDF() below.
    """
    def _with_leading_slash(value):
        return value if value.startswith('/') else '/' + value

    static_url = _with_leading_slash(settings.STATIC_URL or '/static/')
    media_url = getattr(settings, 'MEDIA_URL', None)
    media_url = _with_leading_slash(media_url) if media_url else None
    normalized_uri = _with_leading_slash(uri)

    if normalized_uri.startswith(static_url):
        # IMPORTANT: this must be relative to the static namespace (i.e.
        # WITHOUT the STATIC_URL prefix) — that's what finders.find() and
        # STATIC_ROOT both expect. No leading slash either: on Windows,
        # os.path.join() silently discards everything before a component
        # that starts with a separator, which previously caused
        # STATIC_ROOT to be dropped entirely.
        rel_path = normalized_uri[len(static_url):].lstrip('/')

        found = finders.find(rel_path)
        if found:
            if isinstance(found, (list, tuple)):
                found = found[0]
            return os.path.realpath(found)

        if settings.STATIC_ROOT:
            candidate = os.path.normpath(os.path.join(settings.STATIC_ROOT, rel_path))
            if os.path.isfile(candidate):
                return candidate

    if media_url and normalized_uri.startswith(media_url):
        rel_path = normalized_uri[len(media_url):].lstrip('/')
        media_root = getattr(settings, 'MEDIA_ROOT', None)
        if media_root:
            candidate = os.path.normpath(os.path.join(media_root, rel_path))
            if os.path.isfile(candidate):
                return candidate

    if os.path.isfile(uri):
        # Already an absolute filesystem path.
        return uri

    raise Exception(
        f'pdf_link_callback: could not resolve "{uri}" to a file on disk. '
        f'STATIC_URL={settings.STATIC_URL!r}, STATIC_ROOT={settings.STATIC_ROOT!r}. '
        f'Make sure the logo file actually exists under a static/ directory '
        f'Django knows about (e.g. Sphere/static/images/nova_logo.jpeg, or '
        f'wherever your STATICFILES_DIRS points), and, in production, that '
        f'`collectstatic` has been run.'
    )


def _safe_reverse(name, **kwargs):
    """Resolve a named URL, or None if it isn't wired up in urls.py yet."""
    try:
        return reverse(name, kwargs=kwargs)
    except NoReverseMatch:
        return None


def project_landing_url(project):
    """
    Where a project row/activity entry should link to — whatever page
    reflects the phase the project is actually sitting in right now, so
    clicking it always lands on the next relevant action instead of a
    dead end. Falls back to the project list if a step's URL isn't
    available for some reason.
    """
    quotation = getattr(project, 'quotation', None)
    invoice = getattr(quotation, 'invoice', None) if quotation else None

    if invoice is not None:
        url = _safe_reverse('sphere_invoice', project_id=project.pk)
        if url:
            return url
    if quotation is not None:
        url = _safe_reverse('sphere_quotation', project_id=project.pk)
        if url:
            return url
    if project.has_cost_estimate():
        url = _safe_reverse('sphere_technical_review', project_id=project.pk)
        if url:
            return url
    if project.has_requirements():
        url = _safe_reverse('sphere_estimate_create', project_id=project.pk)
        if url:
            return url
    url = _safe_reverse('sphere_project_edit', pk=project.pk)
    if url:
        return url
    return reverse('sphere_project_list')


def _period_trend(queryset, period_start, prev_start, prev_end):
    """
    Compares how many rows were created in the last 7 days against the
    7 days before that, for the dashboard stat cards' up/down indicator.
    Returns a dict with a direction ('up' / 'down' / 'flat') and a
    percent change, or percent=None when there's no prior-period baseline
    to compare against (so the template can show "New" instead of a
    misleading percentage).
    """
    current = queryset.filter(created_at__date__gte=period_start).count()
    previous = queryset.filter(
        created_at__date__gte=prev_start,
        created_at__date__lte=prev_end,
    ).count()

    if previous == 0:
        if current == 0:
            return {'direction': 'flat', 'percent': 0}
        return {'direction': 'up', 'percent': None}

    percent = round(((current - previous) / previous) * 100)
    direction = 'up' if percent > 0 else 'down' if percent < 0 else 'flat'
    return {'direction': direction, 'percent': abs(percent)}


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
    # REJECTED and COMPLETED are the two terminal states now that
    # Completed & Handed Over exists — everything else (including
    # Approved, In Progress, Paid in Full) is still actively moving.
    completed_projects_qs = Project.objects.filter(status='COMPLETED')
    total_revenue = completed_projects_qs.aggregate(total=Sum('final_amount'))['total'] or Decimal('0.00')
    durations = [days for days in (p.duration_days() for p in completed_projects_qs) if days is not None]
    avg_duration_days = round(sum(durations) / len(durations)) if durations else None

    recent_projects = list(Project.objects.select_related('client')[:5])
    recent_clients = list(Client.objects.all()[:5])

    # Every project row/card on the dashboard is clickable — point it at
    # whatever page reflects that project's current phase.
    for project in recent_projects:
        project.dashboard_url = project_landing_url(project)

    # Dashboard "Recent Activity" feed — projects and clients merged into a
    # single feed ordered by created_at, instead of two separate lists, so
    # the panel reads chronologically the way an activity feed should.
    recent_activity = sorted(
        [{'type': 'project', 'obj': p, 'created_at': p.created_at,
          'url': project_landing_url(p)} for p in recent_projects]
        + [{'type': 'client', 'obj': c, 'created_at': c.created_at,
            'url': reverse('sphere_client_list')} for c in recent_clients],
        key=lambda entry: entry['created_at'],
        reverse=True,
    )[:6]

    # "Projects Overview" chart — number of projects created on each of the
    # last 7 days, oldest first, for the Sales-Overview-style line chart.
    today = timezone.localdate()
    chart_days = [today - timezone.timedelta(days=offset) for offset in range(6, -1, -1)]
    chart_labels = [day.strftime('%a') for day in chart_days]
    chart_values = [
        Project.objects.filter(created_at__date=day).count()
        for day in chart_days
    ]

    # Stat card trend badges — rows created in the last 7 days vs the 7
    # days before that. An approximation (a snapshot count like "Active
    # Projects" isn't purely a function of creation date), but it gives a
    # useful, honest "busier/quieter than last week" signal without
    # needing separate historical snapshots.
    period_start = today - timezone.timedelta(days=6)
    prev_start = today - timezone.timedelta(days=13)
    prev_end = today - timezone.timedelta(days=7)
    stat_trends = {
        'total_clients': _period_trend(Client.objects.all(), period_start, prev_start, prev_end),
        'total_projects': _period_trend(Project.objects.all(), period_start, prev_start, prev_end),
        'lead_projects': _period_trend(
            Project.objects.filter(status='LEAD'), period_start, prev_start, prev_end
        ),
        'active_projects': _period_trend(
            Project.objects.exclude(status__in=['REJECTED', 'COMPLETED']),
            period_start, prev_start, prev_end,
        ),
    }

    context = {
        'total_clients': Client.objects.count(),
        'total_projects': Project.objects.count(),
        'lead_projects': Project.objects.filter(status='LEAD').count(),
        'active_projects': Project.objects.exclude(status__in=['REJECTED', 'COMPLETED']).count(),
        'in_progress_projects': Project.objects.filter(status='IN_PROGRESS').count(),
        'completed_projects': completed_projects_qs.count(),
        'total_revenue': total_revenue,
        'avg_duration_days': avg_duration_days,
        'recent_projects': recent_projects,
        'recent_clients': recent_clients,
        'recent_activity': recent_activity,
        'chart_labels': chart_labels,
        'chart_values': chart_values,
        'stat_trends': stat_trends,
        'stat_card_urls': {
            'total_clients': reverse('sphere_client_list'),
            'total_projects': reverse('sphere_project_list'),
            'lead_projects': f"{reverse('sphere_project_list')}?status=LEAD",
            'active_projects': f"{reverse('sphere_project_list')}?status=active",
        },
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
    projects = Project.objects.select_related('client', 'cost_estimate')

    # Optional ?status= filter — 'active' is a shorthand for "not
    # Rejected and not Completed", matching the dashboard's Active
    # Projects stat card; anything else is matched against the status
    # field directly (e.g. ?status=LEAD from the Leads stat card).
    status_filter = request.GET.get('status')
    if status_filter == 'active':
        projects = projects.exclude(status__in=['REJECTED', 'COMPLETED'])
    elif status_filter:
        projects = projects.filter(status=status_filter)

    return render(request, 'Sphere/project_list.html', {
        'projects': projects,
        'status_filter': status_filter,
    })


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


@pm_login_required
def project_edit_view(request, pk):
    """
    Edit an existing project's details and Functional Requirements
    (Phase 1/2). Reuses ProjectForm/project_form.html as-is — the form
    already handles being bound to an existing instance (pre-populating
    checkboxes from what was saved).

    Most relevant when a Quotation has been Rejected and the PM needs to
    revisit what was actually scoped: changing which functional
    requirements are selected changes what functional_requirements_cost()
    prices, which is what the Functional Requirements Cost line — and
    therefore the quotation — is built from. If a Cost Estimate already
    exists, its feature_requirements_cost is re-synced here so it doesn't
    silently go stale; if it was Approved and the total actually changed,
    it's reopened for re-approval, same as editing Cost Components does
    in Technical Review.
    """
    project = get_object_or_404(Project, pk=pk)

    if request.method == 'POST':
        form = ProjectForm(request.POST, instance=project)
        if form.is_valid():
            updated_project = form.save()

            estimate = getattr(updated_project, 'cost_estimate', None)
            if estimate is not None:
                previous_total = estimate.total_cost()
                was_approved = estimate.is_approved()
                estimate.sync_feature_requirements_cost()

                if was_approved and estimate.total_cost() != previous_total:
                    estimate.reopen()
                    messages.warning(
                        request,
                        'Functional Requirements changed — the Cost Estimate has been '
                        'reopened for review and needs to be re-approved.'
                    )
                estimate.save()

            messages.success(request, f'"{updated_project.project_name}" updated.')
            if estimate is not None:
                return redirect('sphere_technical_review', project_id=updated_project.pk)
            return redirect('sphere_project_list')
    else:
        form = ProjectForm(instance=project)

    return render(request, 'Sphere/project_form.html', {
        'form': form,
        'preselected_client': project.client,
        'category_field_rules_json': json.dumps(Project.CATEGORY_FIELD_RULES),
        'default_field_rule_json': json.dumps(Project.DEFAULT_FIELD_RULE),
        'editing_project': project,
    })


@pm_login_required
def project_requirements_output_view(request, pk):
    """
    On-demand Phase 2 outputs (per the IT PMS workflow): Software
    Requirements Specification (SRS), Feature List, and Initial Project
    Scope — all compiled from whatever was captured in the Phase 2
    requirements-gathering form. Triggered by a 'Generate' button on the
    project detail page rather than automatically on save.

    Currently an in-app summary page; a downloadable Word/PDF version can
    reuse this same context later without touching the model methods.
    """
    project = get_object_or_404(Project.objects.select_related('client', 'project_manager'), pk=pk)

    if not project.has_requirements():
        messages.info(
            request,
            'Complete the Requirements Gathering step for this project before generating the SRS, '
            'Feature List, and Initial Project Scope.'
        )
        return redirect('sphere_project_list')

    context = {
        'project': project,
        'feature_list': project.functional_requirements_display(),
        'initial_scope': project.initial_project_scope(),
        'srs_reference': project.srs_reference(),
        'generated_at': timezone.now(),
    }
    return render(request, 'Sphere/project_output.html', context)


# Statuses a project can still be sitting in when Phase 3 (Estimation) starts.
# Creating an estimate only ever moves status *forward* to 'ESTIMATION' — a
# project already further along (technical review, approved, etc.) keeps
# its current status rather than being pulled backward.
_PRE_ESTIMATION_STATUSES = {'LEAD', 'REQUIREMENTS_GATHERING', 'ANALYSIS', 'RECOMMENDATION'}


@pm_login_required
def cost_estimate_create_view(request, project_id):
    """
    Phase 3 — Project Estimation. One-time creation of a project's Cost
    Estimate (Total Development, Infrastructure, API Subscription, Hosting,
    Domain Registration, SSL Certificate). If an estimate already exists,
    this redirects straight to the Technical Review page (Phase 4) instead
    of letting a second one be created.
    """
    project = get_object_or_404(Project, pk=project_id)

    if project.has_cost_estimate():
        return redirect('sphere_technical_review', project_id=project.pk)

    if not project.has_requirements():
        messages.info(
            request,
            'Complete Requirements Gathering for this project before estimating its cost.'
        )
        return redirect('sphere_project_list')

    if request.method == 'POST':
        form = CostEstimateForm(request.POST, project=project)
        if form.is_valid():
            estimate = form.save(commit=False)
            estimate.project = project
            estimate.prepared_by = request.user
            # Functional Requirements Cost isn't a form field — it's priced
            # automatically from whatever was selected in Phase 2.
            estimate.sync_feature_requirements_cost()
            estimate.save()

            if project.status in _PRE_ESTIMATION_STATUSES:
                project.status = 'ESTIMATION'
                project.save(update_fields=['status'])

            messages.success(
                request,
                f'Cost estimate for "{project.project_name}" created — total KES {estimate.total_cost():,.2f}. '
                f'Send it through Technical Review when ready.'
            )
            return redirect('sphere_technical_review', project_id=project.pk)
    else:
        form = CostEstimateForm(project=project)

    return render(request, 'Sphere/cost_estimate_form.html', {
        'form': form,
        'project': project,
        # Fixed addend for the live JS total — Functional Requirements
        # Cost isn't one of the number inputs on this form.
        'feature_requirements_cost': float(project.functional_requirements_cost()),
        'development_included_requirements': project.development_included_requirements_display(),
    })


@pm_login_required
def technical_review_view(request, project_id):
    """
    Phase 4 — Technical Review. Any PM can review requirements, adjust cost
    components, add technical notes, recalculate, and approve the estimate.

    Two submit actions share this one form:
      - 'save'    Update Cost Components / Add Technical Notes / Recalculate.
                   If the total changes on an already-Approved estimate, it
                   reopens (drops back to Draft) since the approved figure
                   no longer matches what's on record.
      - 'approve' Approve Cost Estimates — locks in the current numbers.
    """
    project = get_object_or_404(Project.objects.select_related('client'), pk=project_id)
    estimate = getattr(project, 'cost_estimate', None)

    if estimate is None:
        messages.info(
            request,
            f'"{project.project_name}" doesn\'t have a cost estimate yet — create one first.'
        )
        return redirect('sphere_estimate_create', project_id=project.pk)

    if request.method == 'POST':
        action = request.POST.get('action', 'save')
        previous_total = estimate.total_cost()
        was_approved = estimate.is_approved()

        form = TechnicalReviewForm(request.POST, instance=estimate)
        if form.is_valid():
            updated_estimate = form.save(commit=False)
            # Functional Requirements Cost isn't edited from this form —
            # keep it in sync with Phase 2 in case requirements changed
            # since the estimate was first created.
            updated_estimate.sync_feature_requirements_cost()

            if was_approved and updated_estimate.total_cost() != previous_total:
                updated_estimate.reopen()
                messages.warning(
                    request,
                    'Cost components changed — the estimate has been reopened for review '
                    'and needs to be re-approved.'
                )

            if action == 'approve':
                updated_estimate.status = CostEstimate.STATUS_APPROVED
                updated_estimate.reviewed_by = request.user
                updated_estimate.approved_at = timezone.now()

            updated_estimate.save()

            if project.status in _PRE_ESTIMATION_STATUSES | {'ESTIMATION'}:
                project.status = 'TECHNICAL_REVIEW'
                project.save(update_fields=['status'])

            if action == 'approve':
                messages.success(
                    request,
                    f'Cost estimate for "{project.project_name}" approved — '
                    f'total KES {updated_estimate.total_cost():,.2f}.'
                )
            else:
                messages.success(request, 'Cost estimate updated.')
            return redirect('sphere_technical_review', project_id=project.pk)
    else:
        form = TechnicalReviewForm(instance=estimate)

    return render(request, 'Sphere/technical_review.html', {
        'form': form,
        'project': project,
        'estimate': estimate,
        'feature_list': project.functional_requirements_display(),
        'feature_cost_breakdown': project.functional_requirements_cost_breakdown(),
        'feature_requirements_cost': float(estimate.feature_requirements_cost),
        'development_included_requirements': project.development_included_requirements_display(),
    })


# Client decisions (Phase 6) that can be recorded against a Sent quotation.
# A PM records these on the client's behalf, since there's no separate
# client-facing portal in this system.
_CLIENT_DECISION_STATUSES = {
    'approve': Quotation.STATUS_APPROVED,
    'reject': Quotation.STATUS_REJECTED,
    'request_revision': Quotation.STATUS_REVISION_REQUESTED,
}

# How a quotation's status maps onto the project's overall status, so the
# project record always reflects where the deal actually stands.
_QUOTATION_STATUS_TO_PROJECT_STATUS = {
    Quotation.STATUS_SENT: 'PROPOSAL_SENT',
    Quotation.STATUS_UNDER_REVIEW: 'CLIENT_REVIEW',
    Quotation.STATUS_APPROVED: 'APPROVED',
    Quotation.STATUS_REJECTED: 'REJECTED',
    Quotation.STATUS_REVISION_REQUESTED: 'CLIENT_REVIEW',
}


@pm_login_required
def quotation_view(request, project_id):
    """
    Phase 5 — Quotation Generation, combined with Phase 6 — Client Review
    & Approval. Only reachable once the Cost Estimate is Approved (Phase
    4); auto-creates the Quotation (status Draft) the first time it's
    opened for an eligible project. From here a PM can:

      - 'save'              Update VAT Rate / Discount / Payment Terms / Validity.
      - 'send'               Mark the quotation Sent to the client.
      - 'approve' / 'reject' / 'request_revision'
                              Record the client's decision (Phase 6), since
                              the client doesn't have direct system access.

    No separate technical proposal document is produced, and — per the
    workflow — the generic 'Taxes' line is represented specifically as VAT.
    """
    project = get_object_or_404(Project.objects.select_related('client'), pk=project_id)
    estimate = getattr(project, 'cost_estimate', None)

    if estimate is None or not estimate.is_approved():
        messages.info(
            request,
            f'"{project.project_name}" needs an Approved Cost Estimate before a quotation can be generated.'
        )
        return redirect('sphere_technical_review', project_id=project.pk)

    quotation, created = Quotation.objects.get_or_create(
        project=project,
        defaults={'generated_by': request.user},
    )

    if request.method == 'POST':
        action = request.POST.get('action', 'save')

        if action in _CLIENT_DECISION_STATUSES:
            client_notes = request.POST.get('client_notes', '').strip()
            quotation.record_client_decision(_CLIENT_DECISION_STATUSES[action], notes=client_notes)
            project.status = _QUOTATION_STATUS_TO_PROJECT_STATUS[quotation.status]
            project.save(update_fields=['status'])
            messages.success(
                request,
                f'Client decision recorded for "{project.project_name}" — {quotation.get_status_display()}.'
            )
            return redirect('sphere_quotation', project_id=project.pk)

        if action == 'revise':
            if quotation.status != Quotation.STATUS_REJECTED:
                messages.error(request, 'Only a rejected quotation can be revised this way.')
                return redirect('sphere_quotation', project_id=project.pk)
            quotation.revise()
            # Back into active flow — mirrors project.status right after the
            # Cost Estimate is approved and before the quotation is sent.
            project.status = 'TECHNICAL_REVIEW'
            project.save(update_fields=['status'])
            messages.success(
                request,
                f'Started a new quotation — {quotation.quotation_number}. '
                f'Review the terms below and send when ready.'
            )
            return redirect('sphere_quotation', project_id=project.pk)

        form = QuotationForm(request.POST, instance=quotation)
        if form.is_valid():
            updated_quotation = form.save(commit=False)

            if action == 'send':
                updated_quotation.mark_sent()  # saves internally
                project.status = _QUOTATION_STATUS_TO_PROJECT_STATUS[Quotation.STATUS_SENT]
                project.save(update_fields=['status'])
                messages.success(
                    request,
                    f'Quotation {updated_quotation.quotation_number} marked as sent — '
                    f'Grand Total KES {updated_quotation.grand_total():,.2f}.'
                )
            else:
                updated_quotation.save()
                messages.success(request, 'Quotation updated.')
            return redirect('sphere_quotation', project_id=project.pk)
    else:
        form = QuotationForm(instance=quotation)

    return render(request, 'Sphere/quotation.html', {
        'form': form,
        'project': project,
        'quotation': quotation,
        'status_form': ProjectStatusForm(instance=project),
    })


@pm_login_required
def quotation_pdf_view(request, project_id):
    """
    Downloadable PDF version of the quotation (Phase 5). Reuses the exact
    same Quotation model methods (line_items, subtotal, vat_amount,
    grand_total, etc.) as the on-screen quotation.html — only the
    presentation template differs, so the numbers can never drift between
    what the PM sees on screen and what gets sent to the client.

    Doesn't require the quotation to be Sent — a PM can pull a PDF of a
    Draft to sanity-check it before sending, same as they can already
    view it on screen.

    Uses xhtml2pdf (pure-Python, no system libraries required) rather than
    WeasyPrint. It only understands basic CSS2.1 — no flexbox/grid — so
    quotation_pdf.html is laid out with plain tables rather than the
    Bootstrap flex classes used in quotation.html.
    """
    project = get_object_or_404(Project.objects.select_related('client'), pk=project_id)
    quotation = get_object_or_404(Quotation, project=project)

    html_string = render_to_string('Sphere/quotation_pdf.html', {
        'project': project,
        'quotation': quotation,
    })

    result = BytesIO()
    pdf = pisa.CreatePDF(src=html_string, dest=result, link_callback=pdf_link_callback)

    if pdf.err:
        return HttpResponse(
            'Something went wrong generating the PDF for this quotation.',
            status=500,
        )

    filename = f'Quotation_{quotation.quotation_number}.pdf'
    response = HttpResponse(result.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# How an Invoice's derived status maps onto the project's overall status —
# mirrors _QUOTATION_STATUS_TO_PROJECT_STATUS above. The first payment
# (however partial) moves a project out of "waiting on the client" and
# into IN_PROGRESS — work is underway — distinct from AWAITING_PAYMENT
# before it and PAID once the final payment lands. PAID itself isn't the
# same as COMPLETED: being fully paid doesn't mean the project has
# actually been delivered/handed over, so that's always a separate,
# explicit step (see project_complete_view / Project.mark_completed()).
_INVOICE_STATUS_TO_PROJECT_STATUS = {
    Invoice.STATUS_AWAITING_PAYMENT: 'AWAITING_PAYMENT',
    Invoice.STATUS_PARTIALLY_PAID: 'IN_PROGRESS',
    Invoice.STATUS_PAID: 'PAID',
}


def _resync_invoice_and_project(invoice, project):
    """Recompute an Invoice's status from its recorded Payments and mirror
    that onto the project's overall status. Called after any Payment is
    added or removed so both stay in step with what's actually been paid,
    without a PM having to set either by hand."""
    invoice.sync_status()
    invoice.save(update_fields=['status', 'updated_at'])

    update_fields = []

    # First payment received, however partial — record when project
    # execution actually started, so Project.duration() has a real start
    # point once the project is later marked Completed.
    if invoice.amount_paid() > Decimal('0.00') and project.started_at is None:
        project.started_at = timezone.now()
        update_fields.append('started_at')

    # Once a project has been marked Completed & Handed Over, payment
    # bookkeeping (e.g. correcting a mis-entered payment) shouldn't
    # silently move it back to an earlier stage — completion is a
    # deliberate, final step.
    if project.status != 'COMPLETED':
        project.status = _INVOICE_STATUS_TO_PROJECT_STATUS[invoice.status]
        update_fields.append('status')

    if update_fields:
        project.save(update_fields=update_fields)



@pm_login_required
def invoice_view(request, project_id):
    """
    Phase 7 — Invoice Generation. Only reachable once the Quotation has
    been client-Approved (Phase 6); auto-creates the Invoice (status
    Awaiting Initial Payment) the first time it's opened for an eligible
    project. The cost breakdown, Discount and VAT pass through unchanged
    from the Quotation. From here a PM can:

      - 'save'           Update the Due Date.
      - 'add_payment'    Record a payment (amount, date, method, what it
                          was for) — an invoice can have any number of
                          these; see Payment/PaymentForm.
      - 'delete_payment' Remove a payment recorded in error.

    Adding or removing a payment re-derives the invoice's status (and the
    project's overall status) from the payment history automatically —
    see _resync_invoice_and_project().

    No contract is drafted by this system, and there's no separate
    client-facing portal — same as Phase 6, the PM records what's
    actually happened on the client's behalf.
    """
    project = get_object_or_404(Project.objects.select_related('client'), pk=project_id)
    quotation = getattr(project, 'quotation', None)

    if quotation is None or not quotation.is_approved():
        messages.info(
            request,
            f'"{project.project_name}" needs a client-Approved quotation before an invoice can be generated.'
        )
        return redirect('sphere_quotation', project_id=project.pk)

    invoice, created = Invoice.objects.get_or_create(
        quotation=quotation,
        defaults={'generated_by': request.user},
    )

    form = InvoiceForm(instance=invoice)
    payment_form = PaymentForm()

    if request.method == 'POST':
        action = request.POST.get('action', 'save')

        if action == 'add_payment':
            payment_form = PaymentForm(request.POST)
            if payment_form.is_valid():
                payment = payment_form.save(commit=False)
                payment.invoice = invoice
                payment.recorded_by = request.user
                payment.save()
                _resync_invoice_and_project(invoice, project)

                if invoice.is_paid():
                    messages.success(
                        request,
                        f'Payment of KES {payment.amount:,.2f} recorded — invoice fully paid, '
                        f'"{project.project_name}" marked Paid in Full. Mark it Completed & '
                        f'Handed Over once delivery is confirmed.'
                    )
                elif project.status == 'IN_PROGRESS' and invoice.payments.count() == 1:
                    messages.success(
                        request,
                        f'Payment of KES {payment.amount:,.2f} recorded — '
                        f'"{project.project_name}" is now In Progress. '
                        f'Outstanding Balance KES {invoice.outstanding_balance():,.2f}.'
                    )
                else:
                    messages.success(
                        request,
                        f'Payment of KES {payment.amount:,.2f} recorded — '
                        f'Outstanding Balance KES {invoice.outstanding_balance():,.2f}.'
                    )
                return redirect('sphere_invoice', project_id=project.pk)

        elif action == 'delete_payment':
            payment = get_object_or_404(Payment, pk=request.POST.get('payment_id'), invoice=invoice)
            payment.delete()
            _resync_invoice_and_project(invoice, project)
            messages.success(request, 'Payment removed — Outstanding Balance recalculated.')
            return redirect('sphere_invoice', project_id=project.pk)

        else:
            form = InvoiceForm(request.POST, instance=invoice)
            if form.is_valid():
                form.save()
                messages.success(request, 'Invoice details updated.')
                return redirect('sphere_invoice', project_id=project.pk)

    return render(request, 'Sphere/invoice.html', {
        'form': form,
        'payment_form': payment_form,
        'project': project,
        'quotation': quotation,
        'invoice': invoice,
        'payments': invoice.payments.all(),
        'status_form': ProjectStatusForm(instance=project),
        'company': SPHERE_COMPANY_PROFILE,
    })


@pm_login_required
def invoice_pdf_view(request, project_id):
    """
    Downloadable PDF version of the invoice (Phase 7). Reuses the exact
    same Invoice/Quotation model methods (total_due, outstanding_balance,
    etc.) as the on-screen invoice.html, same pattern as
    quotation_pdf_view — the numbers can never drift between what the PM
    sees on screen and what gets sent to the client. Uses xhtml2pdf, same
    as quotation_pdf_view, so invoice_pdf.html is laid out with plain
    tables rather than Bootstrap flex classes.
    """
    project = get_object_or_404(Project.objects.select_related('client'), pk=project_id)
    quotation = get_object_or_404(Quotation, project=project)
    invoice = get_object_or_404(Invoice, quotation=quotation)

    html_string = render_to_string('Sphere/invoice_pdf.html', {
        'project': project,
        'quotation': quotation,
        'invoice': invoice,
        'payments': invoice.payments.all(),
        'company': SPHERE_COMPANY_PROFILE,
    })

    result = BytesIO()
    pdf = pisa.CreatePDF(src=html_string, dest=result, link_callback=pdf_link_callback)

    if pdf.err:
        return HttpResponse(
            'Something went wrong generating the PDF for this invoice.',
            status=500,
        )

    filename = f'Invoice_{invoice.invoice_number}.pdf'
    response = HttpResponse(result.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@pm_login_required
def project_status_update_view(request, pk):
    """
    Lets a PM manually override a project's status — to correct a mistaken
    automatic transition, or move it along a step (e.g. Lead ->
    Requirements Gathering) that isn't otherwise driven by a form
    submission elsewhere in the workflow. Deliberately a tiny, standalone
    endpoint (POST-only, one field) rather than folded into any single
    phase view, so the same small form can be embedded on any
    project-related page — quotation.html and invoice.html both post to
    it — and always redirects back to wherever it was submitted from.
    """
    project = get_object_or_404(Project, pk=pk)
    next_url = request.POST.get('next') or reverse('sphere_project_list')

    if request.method == 'POST':
        form = ProjectStatusForm(request.POST, instance=project)
        if form.is_valid():
            form.save()
            messages.success(request, f'"{project.project_name}" status set to {project.get_status_display()}.')
        else:
            messages.error(request, 'Could not update project status.')

    return redirect(next_url)


@pm_login_required
def project_complete_view(request, project_id):
    """
    Final step after Phase 7 — Completed & Handed Over. Only reachable
    once the invoice is fully Paid: being fully paid and actually having
    delivered/handed over the project aren't the same thing, so this is
    always a deliberate, explicit action rather than something a payment
    triggers automatically (see _resync_invoice_and_project, which stops
    short at PAID).

    Snapshots the final amount actually collected and lets the PM record
    handover notes; Project.duration() (started_at -> completed_at) then
    becomes available for reporting once this is set.
    """
    project = get_object_or_404(Project.objects.select_related('client'), pk=project_id)
    quotation = getattr(project, 'quotation', None)
    invoice = getattr(quotation, 'invoice', None) if quotation else None

    if invoice is None or not invoice.is_paid():
        messages.info(
            request,
            f'"{project.project_name}" needs to be fully paid before it can be marked '
            f'Completed & Handed Over.'
        )
        return redirect('sphere_invoice', project_id=project.pk)

    if project.is_completed():
        messages.info(request, f'"{project.project_name}" is already marked Completed & Handed Over.')
        return redirect('sphere_invoice', project_id=project.pk)

    if request.method == 'POST':
        form = ProjectCompletionForm(request.POST)
        if form.is_valid():
            project.mark_completed(
                user=request.user,
                final_amount=invoice.amount_paid(),
                notes=form.cleaned_data['completion_notes'],
            )
            messages.success(
                request,
                f'"{project.project_name}" marked Completed & Handed Over — '
                f'final amount KES {project.final_amount:,.2f}'
                + (f', duration {project.duration_days()} days.' if project.duration_days() is not None else '.')
            )
            return redirect('sphere_invoice', project_id=project.pk)
    else:
        form = ProjectCompletionForm()

    return render(request, 'Sphere/project_complete.html', {
        'form': form,
        'project': project,
        'quotation': quotation,
        'invoice': invoice,
    })