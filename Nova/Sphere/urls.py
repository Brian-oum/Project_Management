from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path('login/', views.SphereLoginView.as_view(), name='sphere_login'),
    path('logout/', views.SphereLogoutView.as_view(), name='sphere_logout'),
    path('register/', views.register_view, name='sphere_register'),

    # Dashboard
    path('', views.dashboard_view, name='sphere_dashboard'),

    # Clients (Phase 1)
    path('clients/', views.client_list_view, name='sphere_client_list'),
    path('clients/new/', views.client_create_view, name='sphere_client_create'),

    # Projects (Phase 1-2)
    path('projects/', views.project_list_view, name='sphere_project_list'),
    path('projects/new/', views.project_create_view, name='sphere_project_create'),
    path('projects/new/<int:client_id>/', views.project_create_view, name='sphere_project_create_for_client'),
    path('projects/<int:pk>/edit/', views.project_edit_view, name='sphere_project_edit'),
    path('projects/<int:pk>/requirements/', views.project_requirements_output_view, name='sphere_project_requirements_output'),

    # Project Estimation (Phase 3) & Technical Review (Phase 4)
    path('projects/<int:project_id>/estimate/new/', views.cost_estimate_create_view, name='sphere_estimate_create'),
    path('projects/<int:project_id>/estimate/review/', views.technical_review_view, name='sphere_technical_review'),

    # Quotation Generation (Phase 5) & Client Review & Approval (Phase 6)
    path('projects/<int:project_id>/quotation/', views.quotation_view, name='sphere_quotation'),
    path('projects/<int:project_id>/quotation/pdf/', views.quotation_pdf_view, name='sphere_quotation_pdf'),

    # Invoice Generation (Phase 7)
    path('projects/<int:project_id>/invoice/', views.invoice_view, name='sphere_invoice'),
    path('projects/<int:project_id>/invoice/pdf/', views.invoice_pdf_view, name='sphere_invoice_pdf'),

    # Manual project status override (embeddable on any project-related page)
    path('projects/<int:pk>/status/', views.project_status_update_view, name='sphere_project_status_update'),
]