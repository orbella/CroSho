from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('', views.home, name='home'),
    path('role-selection/', views.role_selection, name='role_selection'),
    path('register/', views.register, name='register'),
    path('login/', views.user_login, name='login'),
    path('logout/', views.user_logout, name='logout'),
    path('contact/', views.contact, name='contact'),
    path('about-us/', views.about_us, name='about_us'),
    path('terms-of-service/', views.terms_of_service, name='terms_of_service'),
    path('privacy-policy/', views.privacy_policy, name='privacy_policy'),
    path('seller-dashboard/', views.seller_dashboard, name='seller_dashboard'),
    path('delete-product/<int:product_id>/', views.delete_product, name='delete_product'),
    path('edit-product/<int:product_id>/', views.edit_product, name='edit_product'),
    path('buyer-dashboard/', views.buyer_dashboard, name='buyer_dashboard'),
    path('product/<int:product_id>/', views.product_detail, name='product_detail'),
    path('buyer-profile/', views.buyer_profile, name='buyer_profile'),
    path('seller-profile/', views.seller_profile, name='seller_profile'),
    path('shop/', views.shop, name='shop'), 
    path('buy-now/<int:product_id>/', views.buy_now, name='buy_now'),
    path('add-to-cart/<int:product_id>/', views.add_to_cart, name='add_to_cart'),
    path('add_remove_wishlist/', views.add_remove_wishlist, name='add_remove_wishlist'),
    path('view-cart/', views.view_cart, name='view_cart'),
    path('update-cart/', views.update_cart, name='update_cart'),
    path('remove-from-cart/', views.remove_from_cart, name='remove_from_cart'),
    path('checkout/', views.checkout, name='checkout'),
    path('order-confirmation/<int:order_id>/', views.order_confirmation, name='order_confirmation'),
    path('clear-cart/', views.clear_cart, name='clear_cart'),
    path('migrate-cart/', views.migrate_cart, name='migrate_cart'),
    path('newsletter-subscribe/', views.newsletter_subscribe, name='newsletter_subscribe'),
    path('patterns/', views.patterns, name='patterns'),
    path('tutorials/', views.tutorials, name='tutorials'),
    path('yarn-guide/', views.yarn_guide, name='yarn_guide'),
    path('community/', views.community, name='community'),  
    path('edit-profile/', views.edit_profile, name='edit_profile'),
    path('faq/', views.faq_list, name='faq_list'),
    path('faq-for-admin/', views.add_faq, name='add_faq'),
    path('update-profile/', views.update_profile, name='update_profile'),
    path('blog/', views.blog, name='blog'),  # Blog main page 
    path('blog-post/<int:post_id>/', views.blog_post, name='blog_post'),

    
    path('remove-from-whishlist/<int:product_id>/',views.remove_from_wishlist,name="remove_from_wishlist"), 
    # Seller Orders URLs
    path('seller/orders/', views.seller_orders, name='seller_orders'),
    
    path('seller/reviews/', views.seller_reviews, name='seller_reviews'),
    path('seller/reviews/reply/<int:review_id>/', views.reply_to_review, name='reply_to_review'),
    
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('apply-discount/', views.apply_discount, name='apply_discount'),
    path('remove-discount/', views.remove_discount, name='remove_discount'),
    
    path('buyer/orders/', views.buyer_orders, name='buyer_orders'),
    path('buyer/wishlist/', views.buyer_wishlist, name='buyer_wishlist'),
    
    path('checkout/', views.checkout, name='checkout'),
    path('checkout/submit/', views.checkout_submit, name='checkout_submit'),
    path('create-razorpay-order/', views.create_razorpay_order, name='create_razorpay_order'),
    path('payment-success/', views.payment_success, name='payment_success'),
    
    path('order-success/', views.order_success, name='order_success'),
    
    path('product_list/', views.product_list, name='product_list'),
    
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)