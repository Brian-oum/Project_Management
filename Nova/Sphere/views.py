import json
from functools import wraps

from io import BytesIO

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView, LogoutView
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from xhtml2pdf import pisa

from .forms import (
    RegistrationForm, ClientForm, ProjectForm, SphereAuthenticationForm,
    CostEstimateForm, TechnicalReviewForm, QuotationForm, InvoiceForm,
    PaymentForm, ProjectStatusForm,
)
from .models import Client, Project, CostEstimate, Quotation, Invoice, Payment


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
    projects = Project.objects.select_related('client', 'cost_estimate')
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
    pdf = pisa.CreatePDF(src=html_string, dest=result)

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
# mirrors _QUOTATION_STATUS_TO_PROJECT_STATUS above. Both "Awaiting
# Initial Payment" and "Partially Paid" leave the project waiting on the
# client, so both map to the same AWAITING_PAYMENT project status; only a
# fully-paid invoice moves the project to PAID.
_INVOICE_STATUS_TO_PROJECT_STATUS = {
    Invoice.STATUS_AWAITING_PAYMENT: 'AWAITING_PAYMENT',
    Invoice.STATUS_PARTIALLY_PAID: 'AWAITING_PAYMENT',
    Invoice.STATUS_PAID: 'PAID',
}


def _resync_invoice_and_project(invoice, project):
    """Recompute an Invoice's status from its recorded Payments and mirror
    that onto the project's overall status. Called after any Payment is
    added or removed so both stay in step with what's actually been paid,
    without a PM having to set either by hand."""
    invoice.sync_status()
    invoice.save(update_fields=['status', 'updated_at'])
    project.status = _INVOICE_STATUS_TO_PROJECT_STATUS[invoice.status]
    project.save(update_fields=['status'])


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
                        f'"{project.project_name}" marked Paid.'
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
    })

    result = BytesIO()
    pdf = pisa.CreatePDF(src=html_string, dest=result)

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