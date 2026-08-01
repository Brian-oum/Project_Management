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
]