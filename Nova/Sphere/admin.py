from django.contrib import admin
from .models import Profile, Client, Project, CostEstimate, Quotation, Invoice, Payment


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'phone_number')
    list_filter = ('role',)
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'user__email')


class ProjectInline(admin.TabularInline):
    model = Project
    extra = 0
    fields = ('project_name', 'status', 'project_category', 'project_manager')
    show_change_link = True


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = (
        'client_id', 'client_name', 'company_name', 'client_type',
        'phone_number', 'email', 'assigned_sales_rep', 'has_location', 'created_at',
    )
    list_filter = ('client_type', 'industry', 'has_location', 'created_at')
    search_fields = ('client_id', 'client_name', 'company_name', 'email', 'phone_number')
    readonly_fields = ('client_id', 'created_at')
    inlines = [ProjectInline]


class CostEstimateInline(admin.StackedInline):
    model = CostEstimate
    extra = 0
    fields = tuple(f for f, _label in CostEstimate.COST_FIELDS) + (
        'feature_requirements_cost', 'status', 'technical_notes',
        'prepared_by', 'reviewed_by', 'approved_at',
    )
    readonly_fields = ('feature_requirements_cost', 'approved_at')


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        'project_name', 'client', 'status', 'project_category',
        'project_manager', 'preferred_completion_date', 'created_at',
    )
    list_filter = ('status', 'project_category')
    search_fields = ('project_name', 'client__client_name', 'client__client_id')
    autocomplete_fields = ['client']
    readonly_fields = ('created_at', 'updated_at', 'requirements_summary')
    inlines = [CostEstimateInline]

    def requirements_summary(self, obj):
        lines = []
        for group_label, items in obj.functional_requirements_display().items():
            lines.append(f"{group_label}: {', '.join(items)}")
        nfr = obj.non_functional_requirements_display()
        if nfr:
            lines.append(f"Non-Functional: {', '.join(nfr)}")
        return '\n'.join(lines) or 'No requirements captured yet.'
    requirements_summary.short_description = 'Requirements (read-only summary)'


@admin.register(CostEstimate)
class CostEstimateAdmin(admin.ModelAdmin):
    list_display = (
        'project', 'status', 'total_cost_display', 'prepared_by', 'reviewed_by',
        'approved_at', 'updated_at',
    )
    list_filter = ('status',)
    search_fields = ('project__project_name', 'project__client__client_name')
    autocomplete_fields = ['project']
    readonly_fields = ('feature_requirements_cost', 'created_at', 'updated_at', 'approved_at')

    def total_cost_display(self, obj):
        return f"KES {obj.total_cost():,.2f}"
    total_cost_display.short_description = 'Total Cost'


@admin.register(Quotation)
class QuotationAdmin(admin.ModelAdmin):
    list_display = (
        'quotation_number', 'project', 'status', 'grand_total_display',
        'valid_until', 'sent_at', 'decided_at',
    )
    list_filter = ('status',)
    search_fields = ('quotation_number', 'project__project_name', 'project__client__client_name')
    autocomplete_fields = ['project']
    readonly_fields = ('quotation_number', 'created_at', 'updated_at', 'sent_at', 'decided_at')

    def grand_total_display(self, obj):
        return f"KES {obj.grand_total():,.2f}"
    grand_total_display.short_description = 'Grand Total'


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ('amount', 'date_paid', 'method', 'description', 'recorded_by')
    readonly_fields = ('recorded_by',)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = (
        'invoice_number', 'project_name', 'status', 'total_due_display',
        'amount_paid_display', 'outstanding_balance_display', 'due_date',
    )
    list_filter = ('status',)
    search_fields = (
        'invoice_number', 'quotation__quotation_number',
        'quotation__project__project_name', 'quotation__project__client__client_name',
    )
    autocomplete_fields = ['quotation']
    readonly_fields = ('invoice_number', 'created_at', 'updated_at')
    inlines = [PaymentInline]

    def project_name(self, obj):
        return obj.project.project_name
    project_name.short_description = 'Project'

    def total_due_display(self, obj):
        return f"KES {obj.total_due():,.2f}"
    total_due_display.short_description = 'Total Due'

    def amount_paid_display(self, obj):
        return f"KES {obj.amount_paid():,.2f}"
    amount_paid_display.short_description = 'Amount Paid'

    def outstanding_balance_display(self, obj):
        return f"KES {obj.outstanding_balance():,.2f}"
    outstanding_balance_display.short_description = 'Outstanding Balance'


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('invoice', 'amount', 'date_paid', 'method', 'description', 'recorded_by')
    list_filter = ('method', 'date_paid')
    search_fields = ('invoice__invoice_number', 'invoice__quotation__project__project_name', 'description')
    autocomplete_fields = ['invoice']