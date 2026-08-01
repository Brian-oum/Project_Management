from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

User = get_user_model()


class EmailAuthBackend(ModelBackend):
    """
    Authenticates against email + password instead of username + password.
    Falls back gracefully if no match / duplicate emails exist.
    """

    def authenticate(self, request, username=None, password=None, email=None, **kwargs):
        email = email or username  # allow either kwarg name to be passed in
        if email is None or password is None:
            return None
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            return None
        except User.MultipleObjectsReturned:
            user = User.objects.filter(email__iexact=email).order_by('id').first()

        if user and user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None