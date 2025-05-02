from django.db import models
from django.contrib.auth.models import User

class UserProfile(models.Model):
    USER_TYPE_CHOICES = [('buyer', 'Buyer'), ('seller', 'Seller')]
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    profile_picture = models.ImageField(upload_to='profiles/', blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    user_type = models.CharField(max_length=10, choices=USER_TYPE_CHOICES)
    
    

# class Product(models.Model):
#     seller = models.ForeignKey(User, on_delete=models.CASCADE)
#     name = models.CharField(max_length=100)
#     price = models.DecimalField(max_digits=10, decimal_places=2)
#     description = models.TextField()
#     image = models.ImageField(upload_to='products/')
#     created_at = models.DateTimeField(auto_now_add=True)

# class Product(models.Model):
#     id = models.AutoField(primary_key=True)
#     seller = models.ForeignKey(User, on_delete=models.CASCADE, db_column='seller_id')
#     proname = models.CharField(max_length=255)
#     price = models.DecimalField(max_digits=10, decimal_places=2)
#     currency = models.CharField(max_length=10, choices=[('USD', 'USD'), ('INR', 'INR')], default='INR')
#     prodescription = models.TextField(blank=True, null=True)
#     image = models.CharField(max_length=255, blank=True, null=True)
#     category = models.CharField(max_length=50, blank=True, null=True)
#     created_at = models.DateTimeField(auto_now_add=True)

#     class Meta:
#         db_table = 'products'
#         managed = False  # Django won't manage schema changes

#     def __str__(self):
#         return self.proname

#     # Alias for template compatibility
#     @property
#     def name(self):
#         return self.proname

#     @property
#     def description(self):
#         return self.prodescription