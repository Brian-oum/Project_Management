from django.contrib import admin
from .models import Profile, Client, Project


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
        'phone_number', 'email', 'assigned_sales_rep', 'created_at',
    )
    list_filter = ('client_type', 'industry', 'created_at')
    search_fields = ('client_id', 'client_name', 'company_name', 'email', 'phone_number')
    readonly_fields = ('client_id', 'created_at')
    inlines = [ProjectInline]


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        'project_name', 'client', 'status', 'project_category',
        'project_manager', 'preferred_completion_date', 'created_at',
    )
    list_filter = ('status', 'project_category')
    search_fields = ('project_name', 'client__client_name', 'client__client_id')
    autocomplete_fields = ['client']
    readonly_fields = ('created_at', 'updated_at')