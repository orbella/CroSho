from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth.models import User
from .models import UserProfile

@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    if created:
        # Default fallback, or you can skip creation if it's not a registered user via form
        UserProfile.objects.create(user=instance, user_type='buyer')  # Or 'seller'
    else:
        instance.userprofile.save()
