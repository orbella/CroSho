from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.core.files.storage import FileSystemStorage
from django.core.paginator import Paginator
from django.db import connection
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone
from django.contrib.auth.models import User
from datetime import timedelta
import requests
import logging
from decimal import Decimal 
import os
from django.conf import settings
import mimetypes
import json

logger = logging.getLogger(__name__)

# Constants
EXCHANGE_RATE_USD_TO_INR = 83.0
ITEMS_PER_PAGE = 10

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import render


# Helper functions
def dictfetchall(cursor):
    """Return all rows from a cursor as a dict"""
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]

def dictfetchone(cursor):
    """Return single row from cursor as a dict"""
    columns = [col[0] for col in cursor.description]
    row = cursor.fetchone()
    return dict(zip(columns, row)) if row else None

# Role check decorators
from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps

# Role check decorators
def buyer_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if request.session.get('user_type') != 'buyer' and not request.user.is_staff:
            messages.error(request, "You don't have permission to access this page.")
            return redirect('home')
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def seller_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if request.session.get('user_type') != 'seller' and not request.user.is_staff:
            messages.error(request, "You don't have permission to access this page.")
            return redirect('home')
        return view_func(request, *args, **kwargs)
    return _wrapped_view 

def admin_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_staff:
            messages.error(request, "You don't have permission to access this page.")
            return redirect('home')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


# Authentication Views
def role_selection(request):
    if request.user.is_authenticated:
        return redirect('home')
    if request.method == 'POST':
        role = request.POST.get('role')
        if role in ['buyer', 'seller']:
            request.session['user_role'] = role
            return redirect('register')
        messages.error(request, "Invalid role selected.")
    return render(request, 'role_selection.html')

from django.core.mail import send_mail

def register(request):
    if request.user.is_authenticated:
        return redirect('home')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        first_name = request.POST.get('first_name', '')
        last_name = request.POST.get('last_name', '')
        phone_number = request.POST.get('phone_number', '')
        address = request.POST.get('address', '')
        profile_picture = request.FILES.get('profile_picture')
        bio = request.POST.get('bio', '')
        user_type = request.session.get('user_role', 'buyer')

        try:
            # Validate inputs
            if User.objects.filter(username=username).exists():
                messages.error(request, "Username already exists.")
                return render(request, 'register.html')
            if User.objects.filter(email=email).exists():
                messages.error(request, "Email already exists.")
                return render(request, 'register.html')

            # Create Django auth_user
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name
            )

            # Handle profile picture
            profile_picture_path = None
            if profile_picture:
                fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'profiles'))
                filename = fs.save(profile_picture.name, profile_picture)
                profile_picture_path = f"profiles/{filename}"

            # Use AddUser to create custom user data
            with connection.cursor() as cursor:
                cursor.callproc('AddUser', [
                    username, email, password, first_name, last_name,
                    phone_number, address, profile_picture_path, bio, user_type
                ])

            messages.success(request, "Registration successful! Please log in.")
            return redirect('login')

        except Exception as e:
            logger.error(f"Error registering user: {str(e)}")
            messages.error(request, f"Error registering user: {str(e)}")
            if 'user' in locals():
                user.delete()
            return render(request, 'register.html')

    return render(request, 'register.html')

def user_login(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        
        if user is not None:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT id, user_type FROM users WHERE username = %s
                """, [username])
                user_data = cursor.fetchone()
                
                if user_data:
                    user_id, user_type = user_data
                    login(request, user)
                    request.session['user_id'] = user_id
                    request.session['user_type'] = user_type
                    
                    messages.success(request, "You have been successfully logged in.")
                    if user.is_staff:
                        return redirect('admin_dashboard')
                    return redirect('buyer_dashboard' if user_type == 'buyer' else 'seller_dashboard')
        
        messages.error(request, "Invalid username or password.")
    
    return render(request, 'login.html')

def user_logout(request):
    logout(request)
    request.session.flush()
    messages.success(request, "You have been successfully logged out.")
    return redirect('home')

# Buyer Views
@login_required
@buyer_required
def buyer_dashboard(request):
    if request.session.get('user_type') != 'buyer':
        messages.error(request, "You are not authorized to view this page.")
        return redirect('home')

    user_info = {}
    products = []
    reviews = []
    orders = []

    try:
        with connection.cursor() as cursor:
            cursor.callproc('GetBuyerProfile', [request.user.id])

            # Fetch user info
            user_info = dictfetchone(cursor)
            cursor.nextset()

            # Fetch products (wishlisted / purchased)
            products = dictfetchall(cursor)
            cursor.nextset()

            # Fetch reviews
            reviews = dictfetchall(cursor)

        # Fetch past orders separately
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT o.id, o.buyer_id, o.product_id, o.seller_id, o.quantity, o.total_price,
                       o.shipping_address, o.payment_method, o.order_date, 
                       p.proname, p.currency
                FROM orders o
                JOIN products p ON o.product_id = p.id
                WHERE o.buyer_id = %s
                ORDER BY o.order_date DESC
            """, [request.user.id])
            orders = dictfetchall(cursor)

    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"Error fetching buyer dashboard: {str(e)}")
        messages.error(request, "Error loading dashboard. Please try again.")
        return redirect('home')

    return render(request, 'buyer_dashboard.html', {
        'user_info': user_info,
        'products': products,
        'reviews': reviews,
        'orders': orders,
    })

@login_required
@buyer_required
def buyer_profile(request):
    if request.session.get('user_type') != 'buyer':
        messages.error(request, "You are not authorized to view this page.")
        return redirect('home')

    user_info = {}
    products = []
    reviews = []

    try:
        with connection.cursor() as cursor:
            cursor.callproc('GetBuyerProfile', [request.user.id])
            
            # Fetch user info
            user_info = dictfetchone(cursor)
            logger.debug(f"User info fetched: {user_info}")

            # Fetch wishlisted and purchased products
            cursor.nextset()
            products = dictfetchall(cursor)
            logger.debug(f"Fetched {len(products)} products for user {request.user.id}")

            # Fetch reviews
            cursor.nextset()
            reviews = dictfetchall(cursor)
            logger.debug(f"Fetched {len(reviews)} reviews for user {request.user.id}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"Error fetching buyer profile: {str(e)}")
        messages.error(request, "Error loading profile. Please try again.")
        return redirect('home')

    return render(request, 'buyer_profile.html', {
        'user_info': user_info,
        'products': products,
        'reviews': reviews
    })



@login_required
def buyer_orders(request):
    user = request.user
    if user.user_type != 'buyer':
        return render(request, 'error.html', {'message': 'Access denied. Buyer account required.'})

    page_number = request.GET.get('page', 1)
    items_per_page = 10

    with connection.cursor() as cursor:
        cursor.callproc('GetBuyerOrders', [user.id, page_number, items_per_page])
        orders = cursor.fetchall()
        cursor.nextset()
        total_orders = cursor.fetchone()[0]

    paginator = Paginator(orders, items_per_page)
    page_obj = paginator.get_page(page_number)

    context = {
        'orders': page_obj,
        'total_orders': total_orders,
        'page_obj': page_obj,
    }
    return render(request, 'buyer_orders.html', context)

@login_required
def buyer_wishlist(request):
    user = request.user
    if user.user_type != 'buyer':
        return render(request, 'error.html', {'message': 'Access denied. Buyer account required.'})

    page_number = request.GET.get('page', 1)
    items_per_page = 10

    with connection.cursor() as cursor:
        cursor.callproc('GetBuyerWishlist', [user.id, page_number, items_per_page])
        wishlist_items = cursor.fetchall()
        cursor.nextset()
        total_wishlist_items = cursor.fetchone()[0]

    paginator = Paginator(wishlist_items, items_per_page)
    page_obj = paginator.get_page(page_number)

    context = {
        'wishlist_items': page_obj,
        'total_wishlist_items': total_wishlist_items,
        'page_obj': page_obj,
    }
    return render(request, 'buyer_wishlist.html', context)


from django.http import JsonResponse
from django.db import connection
from django.contrib.auth.decorators import login_required
import json

@login_required
@buyer_required
def add_remove_wishlist(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            product_id = data.get('product_id')

            if not product_id:
                return JsonResponse({'success': False, 'message': 'Product ID is required'}, status=400)

            # Ensure the product exists in the catalog
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM products WHERE id = %s", [product_id])
                if cursor.fetchone()[0] == 0:
                    return JsonResponse({'success': False, 'message': 'Product not found'}, status=404)

            # Call the stored procedure to add/remove the product from wishlist
            with connection.cursor() as cursor:
                cursor.callproc('AddOrRemoveWishlist', [request.user.id, product_id])

            return JsonResponse({'success': True, 'message': 'Wishlist updated successfully'})

        except Exception as e:
            return JsonResponse({'success': False, 'message': f'Error: {str(e)}'}, status=500)
    else:
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)



@login_required
def remove_from_wishlist(request,product_id):
    if request.method == 'POST':
        user = request.user
        if user.user_type != 'buyer':
            messages.error(request, 'Access denied. Buyer account required.')
            return redirect('buyer_wishlist')

        with connection.cursor() as cursor:
            cursor.callproc('AddOrRemoveWishlist', [user.id, product_id])
        
        messages.success(request, 'Item removed from wishlist.')
        return redirect('buyer_wishlist')
    return redirect('buyer_wishlist')

from django.shortcuts import redirect

@login_required
@buyer_required
def add_to_cart(request, product_id):
    if request.method == 'POST':
        quantity = int(request.POST.get('quantity', 1))

        try:
            user_id = request.session.get('user_id')

            if not user_id:
                messages.error(request, "User not authenticated.")
                return redirect('login')

            with connection.cursor() as cursor:
                cursor.execute("SELECT id, proname, price, currency FROM products WHERE id = %s", [product_id])
                product = dictfetchone(cursor)

                if not product:
                    messages.error(request, "Product not found.")
                    return redirect('shop')

                # Add to cart
                cursor.callproc('AddToCart', [user_id, product_id, quantity])

                messages.success(request, f"{product['proname']} added to your cart!")
                return redirect('view_cart')   # ✅ directly redirect after success

        except Exception as e:
            logger.error(f"Error adding to cart: {str(e)}")
            messages.error(request, f"Error adding to cart: {str(e)}")
            return redirect('shop')

    messages.error(request, "Invalid request method.")
    return redirect('shop')

from django.core.cache import cache
import requests

def get_exchange_rate():
    cached_rate = cache.get('usd_to_inr')
    if cached_rate:
        return cached_rate
    try:
        response = requests.get('https://api.exchangerate-api.com/v4/latest/USD', timeout=5)
        rate = response.json()['rates']['INR']
        cache.set('usd_to_inr', rate, timeout=3600)  # Cache for 1 hour
        return rate
    except requests.RequestException:
        logger.warning("Failed to fetch exchange rate, using default")
        return getattr(settings, 'EXCHANGE_RATE_USD_TO_INR', 83.0)



from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db import connection, DatabaseError
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

from decimal import Decimal
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db import connection, DatabaseError
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def calculate_shipping_cost(subtotal, threshold=4000, flat_rate=250):
    return 0 if subtotal >= threshold else flat_rate

from decimal import Decimal, InvalidOperation
from django.contrib.auth.decorators import login_required
from django.db import connection, DatabaseError
from django.shortcuts import render
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

# Decorator to ensure user is a buyer
def buyer_required(view_func):
    def wrapper(request, *args, **kwargs):
        if request.session.get('user_type') != 'buyer':
            return render(request, 'error.html', {'message': 'Access denied. Buyer account required.'})
        return view_func(request, *args, **kwargs)
    return wrapper

def safe_decimal(value):
    try:
        return Decimal(str(value).strip()) if value else Decimal('0.00')
    except (InvalidOperation, TypeError, ValueError):
        return Decimal('0.00')

@login_required
@buyer_required
def view_cart(request): 
    user_id = request.session.get('user_id')
    cart_items = []
    subtotal = discount_amount = total = Decimal('0.00')
    shipping_cost = 0
    message = ''
    discount = request.session.get('discount', {})

    EXCHANGE_RATE = {'USD_to_INR': getattr(settings, 'EXCHANGE_RATE_USD_TO_INR', 83.0)}
    FREE_SHIPPING_THRESHOLD = getattr(settings, 'FREE_SHIPPING_THRESHOLD', 4000)
    FREE_ITEM_THRESHOLD = getattr(settings, 'FREE_ITEM_THRESHOLD', 10)

    try:
        # 1. Fetch cart items
        with connection.cursor() as cursor:
            cursor.callproc('GetUserCart', [user_id])
            while cursor.description is None and cursor.nextset():
                pass
            if cursor.description:
                cols = [col[0] for col in cursor.description]
                cart_items = [dict(zip(cols, row)) for row in cursor.fetchall()]

        # 2. Convert price to INR
        for item in cart_items:
            price = float(item.get('price', 0))
            qty = int(item.get('quantity', 0))
            currency = item.get('currency', 'INR')
            price_inr = round(price * EXCHANGE_RATE['USD_to_INR'], 2) if currency == 'USD' else price
            item['price_inr'] = price_inr
            item['total_price_inr'] = round(price_inr * qty, 2)

            # Ensure defaults
            item.setdefault('product_id', '')
            item.setdefault('product_name', 'Unknown Product')
            item.setdefault('sku', 'N/A')
            item.setdefault('image', '')
            item.setdefault('stitch_type', '')
            item.setdefault('max_quantity', 999)

        # 3. Calculate totals and discounts
        discount_code = discount.get('code', '') if discount else ''
        with connection.cursor() as cursor:
            cursor.execute("SET @subtotal=0, @discount_amount=0, @total=0, @message='';")
            cursor.execute(
                "CALL GetCartTotalWithDiscount(%s, %s, @subtotal, @discount_amount, @total, @message);",
                [user_id, discount_code]
            )
            cursor.execute("SELECT @subtotal, @discount_amount, @total, @message;")
            row = cursor.fetchone()
            if row:
                subtotal = safe_decimal(row[0])
                discount_amount = safe_decimal(row[1])
                total = safe_decimal(row[2])
                message = row[3]

        # 4. Shipping cost logic
        shipping_cost = 0 if subtotal >= FREE_SHIPPING_THRESHOLD else 250

        # 5. Suggested patterns (stub)
        suggested_patterns = [{
            'title': f'Sample Pattern {i}',
            'image_url': '/static/images/pattern.jpg',
            'description': 'A lovely crochet pattern for beginners.',
        } for i in range(1, 4)]

        cart_count = len(cart_items)
        items_for_free = max(FREE_ITEM_THRESHOLD - cart_count, 0)

        context = {
            'cart_items': cart_items,
            'subtotal': subtotal,
            'shipping_cost': shipping_cost,
            'discount': discount or None,
            'discount_amount': discount_amount,
            'total': total,
            'discount_message': message,
            'items_for_free': items_for_free,
            'suggested_patterns': suggested_patterns,
            'razorpay_key_id': getattr(settings, 'RAZORPAY_KEY_ID', ''),
            'exchange_rate': EXCHANGE_RATE,
            'free_shipping_threshold': FREE_SHIPPING_THRESHOLD,
        }
        return render(request, 'view_cart.html', context)

    except DatabaseError as e:
        logger.error(f"Database error in view_cart for user_id={user_id} (actual={getattr(request.user, 'id', 'unknown')}): {str(e)}")
        return render(request, 'cart.html', {
            'cart_items': [],
            'error_message': 'Unable to load cart. Please try again later.',
        })

    except Exception as e:
        logger.error(f"Unexpected error in view_cart for user_id={user_id} (actual={getattr(request.user, 'id', 'unknown')}): {str(e)}")
        return render(request, 'cart.html', {
            'cart_items': [],
            'error_message': 'An unexpected error occurred. Please contact support.',
        })
    


    
def product_list(request):
    """View for displaying a paginated list of products with filtering options"""
    # Get filter parameters from request
    category = request.GET.get('category', '')
    stitch_type = request.GET.get('stitch_type', '')
    min_price = request.GET.get('min_price', '')
    max_price = request.GET.get('max_price', '')
    sort = request.GET.get('sort', 'newest')
    search_query = request.GET.get('q', '')
    page_number = request.GET.get('page', 1)

    # Base query
    query = """
        SELECT p.id, p.proname, p.price, p.prodescription, p.image, 
               p.created_at, p.seller_id, u.username, p.currency,
               p.category, p.stitch_type,
               (SELECT AVG(rating) FROM reviews WHERE product_id = p.id) as avg_rating,
               (SELECT COUNT(*) FROM reviews WHERE product_id = p.id) as review_count
        FROM products p
        JOIN users u ON p.seller_id = u.id
        WHERE p.is_active = TRUE
    """
    params = []

    # Add filters
    filters = []
    if category:
        filters.append("p.category = %s")
        params.append(category)
    if stitch_type:
        filters.append("p.stitch_type = %s")
        params.append(stitch_type)
    if min_price:
        filters.append("p.price >= %s")
        params.append(float(min_price))
    if max_price:
        filters.append("p.price <= %s")
        params.append(float(max_price))
    if search_query:
        filters.append("(p.proname LIKE %s OR p.prodescription LIKE %s)")
        params.extend([f"%{search_query}%", f"%{search_query}%"])

    if filters:
        query += " AND " + " AND ".join(filters)

    # Add sorting
    sort_options = {
        'newest': "p.created_at DESC",
        'price_asc': "p.price ASC",
        'price_desc': "p.price DESC",
        'popular': "review_count DESC",
        'rating': "avg_rating DESC"
    }
    query += f" ORDER BY {sort_options.get(sort, 'p.created_at DESC')}"

    try:
        with connection.cursor() as cursor:
            # Get paginated products
            cursor.execute(query + " LIMIT %s OFFSET %s", 
                          params + [ITEMS_PER_PAGE, (int(page_number) - 1) * ITEMS_PER_PAGE])
            products = dictfetchall(cursor)

            # Get total count for pagination
            cursor.execute("SELECT COUNT(*) FROM (" + query + ") as subquery", params)
            total_products = cursor.fetchone()[0]

        # Get filter options for sidebar
        with connection.cursor() as cursor:
            cursor.execute("SELECT DISTINCT category FROM products WHERE is_active = TRUE")
            categories = [row[0] for row in cursor.fetchall()]
            
            cursor.execute("SELECT DISTINCT stitch_type FROM products WHERE is_active = TRUE AND stitch_type IS NOT NULL")
            stitch_types = [row[0] for row in cursor.fetchall()]

        paginator = Paginator(range(total_products), ITEMS_PER_PAGE)
        page_obj = paginator.page(page_number)

        return render(request, 'product_list.html', {
            'products': products,
            'page_obj': page_obj,
            'categories': categories,
            'stitch_types': stitch_types,
            'current_category': category,
            'current_stitch': stitch_type,
            'min_price': min_price,
            'max_price': max_price,
            'sort': sort,
            'search_query': search_query,
            'ITEMS_PER_PAGE': ITEMS_PER_PAGE
        })

    except Exception as e:
        logger.error(f"Error in product_list view: {str(e)}")
        messages.error(request, "Error loading products. Please try again.")
        return redirect('home')
    
from django.conf import settings

# context['RAZORPAY_KEY_ID'] = settings.RAZORPAY_KEY_ID
    
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import connection
import logging

logger = logging.getLogger(__name__)

# Constants
EXCHANGE_RATE_USD_TO_INR = 83.0
ITEMS_PER_PAGE = 10

def dictfetchall(cursor):
    """Return all rows from a cursor as a dict"""
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]

def dictfetchone(cursor):
    """Return single row from cursor as a dict"""
    columns = [col[0] for col in cursor.description]
    row = cursor.fetchone()
    return dict(zip(columns, row)) if row else None

@login_required
@buyer_required
def buyer_orders(request):
    """View to display and manage buyer orders"""
    page_number = request.GET.get('page', 1)

    try:
        with connection.cursor() as cursor:
            # Get orders for this buyer
            cursor.execute("""
                SELECT o.id, o.buyer_id, o.product_id, o.seller_id, o.quantity, 
                       o.total_price, o.shipping_address, o.payment_method, 
                       o.order_date, o.status, o.shipped_date, o.delivered_date,
                       p.proname, p.currency,
                       CASE WHEN p.currency = 'USD' THEN o.total_price * %s ELSE o.total_price END AS total_price_inr,
                       u.username as seller_username
                FROM orders o
                JOIN products p ON o.product_id = p.id
                JOIN users u ON o.seller_id = u.id
                WHERE o.buyer_id = %s
                ORDER BY o.order_date DESC
                LIMIT %s OFFSET %s
            """, [
                EXCHANGE_RATE_USD_TO_INR,
                request.session.get('user_id'),
                ITEMS_PER_PAGE,
                (int(page_number) - 1) * ITEMS_PER_PAGE
            ])
            orders = dictfetchall(cursor)

            # Get total count for pagination
            cursor.execute("""
                SELECT COUNT(*) as total_orders
                FROM orders
                WHERE buyer_id = %s
            """, [request.session.get('user_id')])
            total_orders = dictfetchone(cursor)['total_orders']

        paginator = Paginator(range(total_orders), ITEMS_PER_PAGE)
        page_obj = paginator.page(page_number)

        return render(request, 'buyer_orders.html', {
            'orders': orders,
            'page_obj': page_obj,
            'status_choices': ['Processing', 'Shipped', 'Delivered', 'Cancelled']
        })

    except Exception as e:
        logger.error(f"Error fetching buyer orders: {str(e)}")
        messages.error(request, "Error fetching your orders. Please try again later.")
        return redirect('buyer_dashboard')    


import json
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
@login_required
@buyer_required

@csrf_exempt  # Only if CSRF is handled manually, otherwise use @csrf_protect + middleware
def update_cart(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            product_id = int(data.get('product_id'))
            quantity = int(data.get('quantity'))

            if product_id <= 0 or quantity <= 0:
                return JsonResponse({'success': False, 'message': 'Invalid product or quantity.'})

            # Call your stored procedure here (CheckProductAvailability, UpdateCartItem, etc.)
            with connection.cursor() as cursor:
                cursor.callproc('UpdateCartItem', [request.session['user_id'], product_id, quantity])

            return JsonResponse({'success': True})

        except Exception as e:
            print(e)
            return JsonResponse({'success': False, 'message': 'Error updating quantity. Please try again.'})
    else:
        return JsonResponse({'success': False, 'message': 'Invalid request method'})

from django.core.exceptions import ValidationError

from django.http import JsonResponse
from django.db import connection
from django.contrib.auth.decorators import login_required
import logging
import json

logger = logging.getLogger(__name__)

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.db import connection
from django.contrib.auth.decorators import login_required
import logging
import json

logger = logging.getLogger(__name__)

@login_required
@buyer_required
def remove_from_cart(request):
    if request.method != 'POST':
        logger.error('Invalid request method: %s', request.method)
        return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=405)

    try:
        data = json.loads(request.body)
        product_id = data.get('product_id')
        if not product_id:
            logger.error('Product ID missing in request body')
            return JsonResponse({'success': False, 'message': 'Product ID is required'}, status=400)

        # Call stored procedure to remove the item
        with connection.cursor() as cursor:
            cursor.callproc('RemoveFromCart', [request.user.id, product_id])
        
        # Fetch updated cart totals
        with connection.cursor() as cursor:
            discount_code = request.session.get('discount', {}).get('code', '')
            cursor.execute("SET @subtotal=0, @discount_amount=0, @total=0, @message='';")
            cursor.execute(
                "CALL GetCartTotalWithDiscount(%s, %s, @subtotal, @discount_amount, @total, @message);",
                [request.user.id, discount_code]
            )
            cursor.execute("SELECT @subtotal, @discount_amount, @total, @message;")
            row = cursor.fetchone()
            if not row:
                logger.error('Failed to fetch updated cart totals')
                raise ValidationError('Failed to fetch updated cart totals')

            subtotal, discount_amount, total, message = row or (0, 0, 0, '')

        logger.info('Item removed successfully. Updated cart totals - Subtotal: %f, Discount: %f, Total: %f', subtotal, discount_amount, total)

        return JsonResponse({
            'success': True,
            'message': 'Item removed from cart',
            'cart_totals': {
                'subtotal': float(subtotal),
                'discount': float(discount_amount),
                'total': float(total)
            }
        })
    
    except ValidationError as e:
        logger.error('Validation error: %s', str(e))
        return JsonResponse({'success': False, 'message': str(e)}, status=400)
    
    except Exception as e:
        logger.error('Unexpected error: %s', str(e))
        return JsonResponse({'success': False, 'message': 'Error removing item from cart'}, status=500)
    
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import connection
import logging

logger = logging.getLogger(__name__)

EXCHANGE_RATE_USD_TO_INR = 83.0  # Update as needed


EXCHANGE_RATE_USD_TO_INR = 83.0  # Update if needed


def dictfetchall(cursor):
    """Converts cursor result to a list of dictionaries."""
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import connection
import logging

logger = logging.getLogger(__name__)

EXCHANGE_RATE_USD_TO_INR = 83  # Replace this with actual rate

def dictfetchall(cursor):
    "Return all rows from a cursor as a dict"
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]

# def payment_view(request):
#     # Assume you retrieve the order object here
#     return render(request, 'your_payment_template.html', {
#         'order': order,
#         'RAZORPAY_KEY_ID': settings.RAZORPAY_KEY_ID
#     })


@login_required
def checkout(request):
    user_type = request.session.get('user_type')
    if user_type != 'buyer': 
        return render(request, 'error.html', {'message': 'Access denied. Buyer account required.'})
    

    # Fetch cart items
    with connection.cursor() as cursor:
        cursor.callproc('GetUserCart', [request.user.id])
        cart_items = cursor.fetchall()
        columns = [col[0] for col in cursor.description] 
        cart_items = [dict(zip(columns, item)) for item in cart_items]

    if not cart_items:
        return render(request, 'create_razorpay_order.html', {'is_empty': True})

    # Convert prices to INR
    USD_TO_INR = 83
    cart_total_inr = 0
    for item in cart_items:
        if item['currency'] == 'USD':
            item['total_price'] = item['price'] * item['quantity']
            item['total_price_inr'] = item['total_price'] * USD_TO_INR
        else:
            item['total_price_inr'] = item['total_price']
        cart_total_inr += item['total_price_inr']

    # Shipping cost
    shipping_cost_inr = 500 if cart_total_inr < 4000 else 0

    # Discount (example; adjust based on your logic)
    discount_amount_inr = 0  # Replace with actual discount logic

    # Total
    total_inr = cart_total_inr + shipping_cost_inr - discount_amount_inr

    context = {
        'cart_items': cart_items,
        'cart_total_inr': cart_total_inr,
        'shipping_cost_inr': shipping_cost_inr,
        'discount_amount_inr': discount_amount_inr,
        'total_inr': total_inr,
        'RAZORPAY_KEY_ID': settings.RAZORPAY_KEY_ID,
    }
    return render(request, 'checkout.html', context)



# crosho/views.py
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST
from django.conf import settings
from django.http import JsonResponse
import razorpay, json

@require_POST
@csrf_protect
def create_razorpay_order(request):
    if request.session.get('user_type') != 'buyer':
        return JsonResponse({'success': False, 'message': 'Only buyers can create orders.'}, status=403)

    try:
        data = json.loads(request.body)
        amount_inr = float(data.get('amount_inr', 0))
        if amount_inr <= 0:
            return JsonResponse({'success': False, 'message': 'Invalid amount.'}, status=400)

        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        order_data = {
            'amount': int(amount_inr * 100),
            'currency': 'INR',
            'payment_capture': 1
        }
        order = client.order.create(data=order_data)
        return JsonResponse({'success': True, 'order': order})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)

client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

@login_required
def order_success(request):
    return render(request, 'order_success.html')

@csrf_exempt
def payment_success(request):
    if request.method == "POST":
        payment_id = request.POST.get('razorpay_payment_id')
        order_id = request.POST.get('razorpay_order_id')
        signature = request.POST.get('razorpay_signature')

        # Verify payment signature (optional but recommended)
        try:
            client.utility.verify_payment_signature({
                'razorpay_order_id': order_id,
                'razorpay_payment_id': payment_id,
                'razorpay_signature': signature
            })
            # Save the payment info to DB
            return render(request, 'success.html')
        except:
            return render(request, 'failure.html')


# crosho/views.py
from django.shortcuts import redirect
from django.contrib import messages
import razorpay
import hmac
import hashlib

@require_POST
@login_required
def checkout_submit(request):
    if request.user.user_type != 'buyer':
        messages.error(request, 'Only buyers can checkout.')
        return redirect('checkout')

    payment_method = request.POST.get('payment_method')
    preferred_currency = request.POST.get('preferred_currency', 'INR')

    # Validate shipping information
    shipping_info = {
        'first_name': request.POST.get('first_name'),
        'last_name': request.POST.get('last_name'),
        'email': request.POST.get('email'),
        'shipping_address': request.POST.get('shipping_address'),
        'city': request.POST.get('city'),
        'state': request.POST.get('state'),
        'zip_code': request.POST.get('zip_code'),
        'country': request.POST.get('country'),
        'phone': request.POST.get('phone'),
    }
    if not all(shipping_info.values()):
        messages.error(request, 'Please fill in all shipping information.')
        return redirect('checkout')

    # Fetch cart items
    with connection.cursor() as cursor:
        cursor.callproc('GetUserCart', [request.user.id])
        cart_items = cursor.fetchall()
        columns = [col[0] for col in cursor.description]
        cart_items = [dict(zip(columns, item)) for item in cart_items]

    if not cart_items:
        messages.error(request, 'Your cart is empty.')
        return redirect('view_cart')

    # Calculate total in INR
    USD_TO_INR = 83
    cart_total_inr = sum(item['total_price'] * USD_TO_INR if item['currency'] == 'USD' else item['total_price'] for item in cart_items)
    shipping_cost_inr = 500 if cart_total_inr < 4000 else 0
    discount_amount_inr = 0  # Replace with actual discount logic
    total_inr = cart_total_inr + shipping_cost_inr - discount_amount_inr

    # Handle Razorpay payment verification
    if payment_method == 'razorpay':
        payment_id = request.POST.get('razorpay_payment_id')
        if not payment_id:
            messages.error(request, 'Razorpay payment ID missing.')
            return redirect('checkout')

        # Verify payment (example; implement actual verification)
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        try:
            payment = client.payment.fetch(payment_id)
            if payment['status'] != 'captured':
                messages.error(request, 'Payment not captured.')
                return redirect('checkout')
        except Exception as e:
            messages.error(request, f'Payment verification failed: {str(e)}')
            return redirect('checkout')

    # Create order (example; adjust to your schema)
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO orders (buyer_id, total_amount, currency, payment_method, status, shipping_address, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
            """, [request.user.id, total_inr, preferred_currency, payment_method, 'pending',
                  f"{shipping_info['shipping_address']}, {shipping_info['city']}, {shipping_info['state']} {shipping_info['zip_code']}, {shipping_info['country']}"])
            order_id = cursor.lastrowid

            for item in cart_items:
                cursor.execute("""
                    INSERT INTO order_items (order_id, product_id, quantity, price)
                    VALUES (%s, %s, %s, %s)
                """, [order_id, item['product_id'], item['quantity'], item['price'] * USD_TO_INR if item['currency'] == 'USD' else item['price']])

        # Clear cart
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM user_carts WHERE user_id = %s", [request.user.id])

        messages.success(request, 'Order placed successfully!')
        return redirect('order_confirmation', order_id=order_id)
    except Exception as e:
        messages.error(request, f'Error placing order: {str(e)}')
        return redirect('checkout')

def apply_discount(request):
    if request.method == 'POST':
        discount_code = request.POST.get('code', '').strip()
        user_id = request.user.id
        
        with connection.cursor() as cursor:
            # First get cart total
            cursor.execute("""
                SELECT IFNULL(SUM(p.price * uc.quantity), 0)
                FROM user_carts uc
                JOIN products p ON uc.product_id = p.id
                WHERE uc.user_id = %s
            """, [user_id])
            cart_total = cursor.fetchone()[0]
            
            # Apply discount
            cursor.callproc('ApplyDiscount', [
                user_id, 
                discount_code, 
                float(cart_total),
                0,  # out param - will be set
                '',  # out param - will be set
                ''   # out param - will be set
            ])
            
            # Get output parameters
            results = cursor.fetchall()
            if results:
                discount_amount = results[0][0]
                discount_type = results[0][1]
                message = results[0][2]
                
                if discount_amount > 0:
                    request.session['discount'] = {
                        'code': discount_code,
                        'type': discount_type,
                        'amount': float(discount_amount),
                        'message': message
                    }
                    messages.success(request, message)
                else:
                    messages.error(request, message)
                    if 'discount' in request.session:
                        del request.session['discount']
    
    return redirect('view_cart')

def remove_discount(request):
    if 'discount' in request.session:
        with connection.cursor() as cursor:
            cursor.callproc('RemoveDiscount', [
                request.user.id,
                ''  # out param
            ])
            results = cursor.fetchall()
            if results:
                messages.success(request, results[0][0])
        del request.session['discount']
    return redirect('view_cart')
@login_required
@buyer_required
def buy_now(request, product_id):
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT p.id, p.proname, p.price, p.prodescription, p.image, 
                       p.seller_id, u.username as seller_name, p.currency
                FROM products p
                JOIN users u ON p.seller_id = u.id
                WHERE p.id = %s
            """, [product_id])
            product = dictfetchone(cursor)
            
            if not product:
                messages.error(request, "Product not found.")
                return redirect('shop')

        if request.method == 'POST':
            quantity = int(request.POST.get('quantity', 1))
            shipping_address = request.POST.get('shipping_address')
            payment_method = request.POST.get('payment_method')
            
            if quantity < 1:
                messages.error(request, "Quantity must be at least 1.")
                return render(request, 'buynow.html', {'product': product})
            
            if not shipping_address or not payment_method:
                messages.error(request, "Please provide shipping address and payment method.")
                return render(request, 'buynow.html', {'product': product})
            
            total_price = product['price'] * quantity
            
            with connection.cursor() as cursor:
                cursor.callproc('CreateOrder', [
                    request.user.id,
                    product_id,
                    product['seller_id'],
                    quantity,
                    float(total_price),
                    shipping_address,
                    payment_method
                ])
                
                cursor.execute("SELECT LAST_INSERT_ID()")
                order_id = cursor.fetchone()[0]
            
            messages.success(request, "Order placed successfully!")
            return redirect('order_confirmation', order_id=order_id)

        return render(request, 'buynow.html', {'product': product})

    except Exception as e:
        logger.error(f"Error in buy_now: {str(e)}")
        messages.error(request, "Error processing your order. Please try again.")
        return redirect('product_detail', product_id=product_id)

@login_required
@buyer_required
def order_confirmation(request, order_id):
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT o.id, o.buyer_id, o.product_id, o.seller_id, o.quantity, o.total_price,
                       o.shipping_address, o.payment_method, o.order_date, p.proname, p.currency
                FROM orders o
                JOIN products p ON o.product_id = p.id
                WHERE o.id = %s AND o.buyer_id = %s
            """, [order_id, request.user.id])
            order = dictfetchone(cursor)
            
            if not order:
                messages.error(request, "Order not found.")
                return redirect('buyer_dashboard')
            
        return render(request, 'order_confirmation.html', {'order': order})

    except Exception as e:
        logger.error(f"Error fetching order: {str(e)}")
        messages.error(request, "Error fetching order details.")
        return redirect('buyer_dashboard')

# Seller Views
# Seller Dashboard View
@login_required
@seller_required
def seller_dashboard(request):
    try:
        user_id = request.session.get('user_id')

        if not user_id:
            messages.error(request, "Session expired. Please login again.")
            return redirect('login')

        # Fetch seller information
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, username, email, first_name, last_name, phone_number, 
                       address, profile_picture, bio
                FROM users
                WHERE id = %s
            """, [user_id])
            user_data = dictfetchone(cursor)

        if not user_data:
            messages.error(request, "Seller not found. Please login again.")
            return redirect('login')

        # Fetch seller's products
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, proname, price, currency, category, prodescription, 
                       image, created_at, stitch_type
                FROM products
                WHERE seller_id = %s
                ORDER BY created_at DESC
            """, [user_id])
            products = dictfetchall(cursor)

        # Fetch seller stats (total products and total sales)
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(id) AS product_count,
                    COALESCE(SUM(total_price), 0) AS total_sales
                FROM orders
                WHERE seller_id = %s
            """, [user_id])
            stats = dictfetchone(cursor)

        return render(request, 'seller_dashboard.html', {
            'user_info': user_data,
            'products': products,
            'stats': stats,
            'stitch_types': ['granny', 'amigurumi', 'lace', 'cable', 'tunisian']
        })

    except Exception as e:
        logger.error(f"Error fetching seller dashboard: {str(e)}")
        messages.error(request, "Error loading dashboard. Please try again.")
        return redirect('home')

@login_required
@seller_required
def seller_dashboard(request):
    try:
        user_id = request.session.get('user_id')

        if not user_id:
            messages.error(request, "Session expired. Please login again.")
            return redirect('login')

        # Handle product addition
        if request.method == 'POST' and 'add_product' in request.POST:
            # Fetch form data
            name = request.POST['name']
            price = request.POST['price']
            currency = request.POST['currency']
            category = request.POST['category']
            stitch_type = request.POST.get('stitch_type', '')
            description = request.POST['description']
            image = request.FILES.get('image')

            if image:
                from django.core.files.storage import FileSystemStorage
                fs = FileSystemStorage()
                filename = fs.save(image.name, image)
                image_url = fs.url(filename)
            else:
                image_url = ''

            # Insert new product
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO products (seller_id, proname, price, currency, category, stitch_type, prodescription, image, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """, [
                    user_id, name, price, currency, category, stitch_type, description, image_url
                ])
            
            messages.success(request, "Product added successfully!")
            return redirect('seller_dashboard')  # Important to avoid form re-submit on refresh

        # Fetch seller information
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, username, email, first_name, last_name, phone_number, 
                       address, profile_picture, bio
                FROM users
                WHERE id = %s
            """, [user_id])
            user_data = dictfetchone(cursor)

        if not user_data:
            messages.error(request, "Seller not found. Please login again.")
            return redirect('login')

        # Fetch seller's products
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, proname, price, currency, category, prodescription, 
                       image, created_at, stitch_type
                FROM products
                WHERE seller_id = %s
                ORDER BY created_at DESC
            """, [user_id])
            products = dictfetchall(cursor)

        # Fetch seller stats (total products and total sales)
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(id) AS product_count,
                    COALESCE(SUM(total_price), 0) AS total_sales
                FROM orders
                WHERE seller_id = %s
            """, [user_id])
            stats = dictfetchone(cursor)

        return render(request, 'seller_dashboard.html', {
            'user_info': user_data,
            'products': products,
            'stats': stats,
            'stitch_types': ['granny', 'amigurumi', 'lace', 'cable', 'tunisian']
        })

    except Exception as e:
        logger.error(f"Error fetching seller dashboard: {str(e)}")
        messages.error(request, "Error loading dashboard. Please try again.")
        return redirect('home')


from django.contrib.auth.decorators import login_required
from django.core.files.storage import FileSystemStorage
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
import os
import logging

logger = logging.getLogger(__name__)

def dictfetchone(cursor):
    "Return all rows from a cursor as a dict"
    desc = cursor.description
    row = cursor.fetchone()
    if row:
        return dict(zip([col[0] for col in desc], row))
    return None

@login_required
@seller_required
def edit_product(request, product_id):
    try:
        seller_id = request.session.get('user_id')

        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, proname, price, prodescription, image, 
                       currency, category, stitch_type
                FROM products
                WHERE id = %s AND seller_id = %s
            """, [product_id, seller_id])
            product = dictfetchone(cursor)
            
            if not product:
                messages.error(request, "Product not found or unauthorized.")
                return redirect('seller_dashboard')

        if request.method == 'POST':
            proname = request.POST.get('name')
            price = request.POST.get('price')
            prodescription = request.POST.get('description')
            currency = request.POST.get('currency', 'USD')
            category = request.POST.get('category')
            stitch_type = request.POST.get('stitch_type')
            image = request.FILES.get('image')

            # Validation
            errors = {}
            if not proname:
                errors['name'] = "Product name is required."
            if not price or float(price) <= 0:
                errors['price'] = "Valid price is required."
            if currency not in ['INR', 'USD']:
                errors['currency'] = "Valid currency is required."
            if not category:
                errors['category'] = "Category is required."
            if not prodescription:
                errors['description'] = "Description is required."
            if image:
                if image.size > 5 * 1024 * 1024:
                    errors['image'] = "Image size must be less than 5MB."
                elif not image.content_type.startswith('image/'):
                    errors['image'] = "File must be an image."

            if not errors:
                try:
                    image_path = product['image']  # default: keep existing

                    if image:
                        fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'products'))
                        filename = fs.save(image.name, image)
                        image_path = f"products/{filename}"

                        # Delete old image properly
                        if product['image']:
                            old_image_path = os.path.join(settings.MEDIA_ROOT, product['image'])
                            if os.path.exists(old_image_path):
                                os.remove(old_image_path)

                    with connection.cursor() as cursor:
                        cursor.callproc('EditProduct', [
                            product_id, 
                            seller_id,
                            proname,
                            float(price),
                            currency,
                            prodescription,
                            image_path,
                            category,
                            stitch_type
                        ])

                    messages.success(request, "Product updated successfully!")
                    return redirect('seller_dashboard')

                except Exception as e:
                    logger.error(f"Error updating product: {str(e)}")
                    messages.error(request, "Error updating product. Please try again.")

                    # Cleanup new uploaded image if error happened
                    if 'image_path' in locals() and image_path != product['image']:
                        fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'products'))
                        fs.delete(image_path)

            else:
                for error in errors.values():
                    messages.error(request, error)

        return render(request, 'edit_product.html', {
            'product': product,
            'stitch_types': ['granny', 'amigurumi', 'lace', 'cable', 'tunisian'],
            'MEDIA_URL': settings.MEDIA_URL,
        })

    except Exception as e:
        logger.error(f"Error in edit_product: {str(e)}")
        messages.error(request, "Error loading product. Please try again.")
        return redirect('seller_dashboard')



@login_required
@seller_required
def delete_product(request, product_id):
    if request.method == 'POST':
        try:
            seller_id = request.session.get('user_id')  # ✅ Correct way to get seller_id

            with connection.cursor() as cursor:
                # Verify product belongs to seller
                cursor.execute("""
                    SELECT image 
                    FROM products 
                    WHERE id = %s AND seller_id = %s
                """, [product_id, seller_id])
                product = cursor.fetchone()

                if not product:
                    messages.error(request, "Product not found or unauthorized.")
                    return redirect('seller_dashboard')

                image_path = product[0]

                # ✨ Call DeleteProduct procedure with both product_id and seller_id
                cursor.callproc('DeleteProduct', [product_id, seller_id])

                # Delete image file if exists
                if image_path:
                    fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'products'))
                    try:
                        fs.delete(image_path)
                    except Exception as e:
                        logger.warning(f"Failed to delete image file: {str(e)}")

            messages.success(request, "Product deleted successfully!")

        except Exception as e:
            logger.error(f"Error deleting product: {str(e)}")
            messages.error(request, f"Error deleting product. Please try again.")

    return redirect('seller_dashboard')




@login_required
@seller_required
def seller_orders(request):
    try:
        page_number = int(request.GET.get('page', 1))
        seller_id = request.session.get('user_id')

        with connection.cursor() as cursor:
            # Get paginated orders (no o.status since orders table doesn't have it)
            cursor.execute("""
                SELECT o.id, o.buyer_id, o.product_id, o.quantity, o.total_price,
                       o.shipping_address, o.payment_method, o.order_date,
                       p.proname, p.currency, u.username as buyer_name,
                       CASE WHEN p.currency = 'USD' THEN o.total_price * %s ELSE o.total_price END AS total_price_inr
                FROM orders o
                JOIN products p ON o.product_id = p.id
                JOIN users u ON o.buyer_id = u.id
                WHERE o.seller_id = %s
                ORDER BY o.order_date DESC
                LIMIT %s OFFSET %s
            """, [EXCHANGE_RATE_USD_TO_INR, seller_id, ITEMS_PER_PAGE, (page_number - 1) * ITEMS_PER_PAGE])
            orders = dictfetchall(cursor)

            # Get total count for pagination
            cursor.execute("""
                SELECT COUNT(*) as total_orders
                FROM orders
                WHERE seller_id = %s
            """, [seller_id])
            total_orders = dictfetchone(cursor)['total_orders']

        paginator = Paginator(range(total_orders), ITEMS_PER_PAGE)
        page_obj = paginator.page(page_number)

        return render(request, 'seller_orders.html', {
            'orders': orders,
            'page_obj': page_obj,
            'status_choices': ['Processing', 'Shipped', 'Delivered', 'Cancelled']  # For order status updates if you add later
        }) 

    except Exception as e:
        logger.error(f"Error fetching seller orders: {str(e)}")
        messages.error(request, "Error fetching orders. Please try again.")
        return redirect('seller_dashboard')

@login_required
@seller_required
def update_order_status(request, order_id):
    if request.method == 'POST':
        new_status = request.POST.get('new_status')
        valid_statuses = ['Processing', 'Shipped', 'Delivered', 'Cancelled']
        
        if new_status not in valid_statuses:
            messages.error(request, "Invalid status.")
            return redirect('seller_orders')
        
        try:
            with connection.cursor() as cursor:
                # Verify order belongs to seller
                cursor.execute("""
                    SELECT id FROM orders 
                    WHERE id = %s AND seller_id = %s
                """, [order_id, request.user.id])
                if not cursor.fetchone():
                    messages.error(request, "Order not found or unauthorized.")
                    return redirect('seller_orders')
                
                # Update status
                cursor.callproc('UpdateOrderStatus', [order_id, new_status])
                
                messages.success(request, f"Order status updated to {new_status}.")
        
        except Exception as e:
            logger.error(f"Error updating order status: {str(e)}")
            messages.error(request, "Error updating order status.")
    
    return redirect('seller_orders')

@login_required
@seller_required
def seller_reviews(request):
    try:
        page_number = request.GET.get('page', 1)
        
        with connection.cursor() as cursor:
            # Get paginated reviews
            cursor.execute("""
                SELECT r.id, r.product_id, r.buyer_id, r.rating, r.comment, 
                       r.created_at, p.proname, u.username as buyer_name
                FROM reviews r
                JOIN products p ON r.product_id = p.id
                JOIN users u ON r.buyer_id = u.id
                WHERE p.seller_id = %s
                ORDER BY r.created_at DESC
                LIMIT %s OFFSET %s
            """, [request.user.id, ITEMS_PER_PAGE, (int(page_number) - 1) * ITEMS_PER_PAGE])
            reviews = dictfetchall(cursor)

            # Get total count for pagination
            cursor.execute("""
                SELECT COUNT(*) as total_reviews
                FROM reviews r
                JOIN products p ON r.product_id = p.id
                WHERE p.seller_id = %s
            """, [request.user.id])
            total_reviews = dictfetchone(cursor)['total_reviews']

            # Get average rating
            cursor.execute("""
                SELECT AVG(r.rating) as avg_rating, COUNT(r.id) as review_count
                FROM reviews r
                JOIN products p ON r.product_id = p.id
                WHERE p.seller_id = %s
            """, [request.user.id])
            rating_stats = dictfetchone(cursor)

        paginator = Paginator(range(total_reviews), ITEMS_PER_PAGE)
        page_obj = paginator.page(page_number)

        return render(request, 'seller_reviews.html', {
            'reviews': reviews,
            'page_obj': page_obj,
            'rating_stats': rating_stats,
            'star_range': range(1, 6)
        })

    except Exception as e:
        logger.error(f"Error fetching seller reviews: {str(e)}")
        messages.error(request, "Error fetching reviews. Please try again.")
        return redirect('seller_dashboard')

@login_required
@seller_required
def reply_to_review(request, review_id):
    if request.method == 'POST':
        reply_text = request.POST.get('reply_text', '').strip()
        
        try:
            with connection.cursor() as cursor:
                # Verify review is for seller's product
                cursor.execute("""
                    SELECT p.seller_id 
                    FROM reviews r
                    JOIN products p ON r.product_id = p.id
                    WHERE r.id = %s
                """, [review_id])
                result = cursor.fetchone()
                
                if not result or result[0] != request.user.id:
                    messages.error(request, "Review not found or unauthorized.")
                    return redirect('seller_reviews')
                
                # Add reply
                cursor.callproc('AddSellerReply', [review_id, reply_text])
                
                messages.success(request, "Reply added successfully.")
        
        except Exception as e:
            logger.error(f"Error adding reply to review: {str(e)}")
            messages.error(request, "Error adding reply. Please try again.")
    
    return redirect('seller_reviews')

# Admin Views
@login_required
@admin_required
def admin_dashboard(request):
    try:
        with connection.cursor() as cursor:
            # Get stats
            cursor.execute("""
                SELECT 
                    (SELECT COUNT(*) FROM users WHERE user_type = 'buyer') as buyer_count,
                    (SELECT COUNT(*) FROM users WHERE user_type = 'seller') as seller_count,
                    (SELECT COUNT(*) FROM products) as product_count,
                    (SELECT COUNT(*) FROM orders) as order_count,
                    (SELECT SUM(total_price) FROM orders WHERE status = 'Delivered') as total_sales
            """)
            stats = dictfetchone(cursor)
            
            # Get recent orders
            cursor.execute("""
                SELECT o.id, o.buyer_id, o.product_id, o.seller_id, o.quantity, o.total_price,
                       o.shipping_address, o.payment_method, o.order_date, o.status,
                       p.proname, u1.username as buyer_name, u2.username as seller_name
                FROM orders o
                JOIN products p ON o.product_id = p.id
                JOIN users u1 ON o.buyer_id = u1.id
                JOIN users u2 ON o.seller_id = u2.id
                ORDER BY o.order_date DESC
                LIMIT 5
            """)
            recent_orders = dictfetchall(cursor)
            
            # Get recent products
            cursor.execute("""
                SELECT p.id, p.proname, p.price, p.currency, p.created_at, u.username as seller_name
                FROM products p
                JOIN users u ON p.seller_id = u.id
                ORDER BY p.created_at DESC
                LIMIT 5
            """)
            recent_products = dictfetchall(cursor)

        return render(request, 'admin_dashboard.html', {
            'stats': stats,
            'recent_orders': recent_orders,
            'recent_products': recent_products
        })

    except Exception as e:
        logger.error(f"Error loading admin dashboard: {str(e)}")
        messages.error(request, "Error loading dashboard. Please try again.")
        return redirect('home')

@login_required
@admin_required
def manage_users(request):
    try:
        page_number = request.GET.get('page', 1)
        user_type = request.GET.get('type', 'all')
        
        base_query = "SELECT id, username, email, user_type, created_at FROM users"
        count_query = "SELECT COUNT(*) as total_users FROM users"
        params = []
        
        if user_type in ['buyer', 'seller']:
            base_query += " WHERE user_type = %s"
            count_query += " WHERE user_type = %s"
            params.append(user_type)
        
        base_query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([ITEMS_PER_PAGE, (int(page_number) - 1) * ITEMS_PER_PAGE])
        
        with connection.cursor() as cursor:
            cursor.execute(count_query, params[:1] if len(params) > 2 else [])
            total_users = dictfetchone(cursor)['total_users']
            
            cursor.execute(base_query, params)
            users = dictfetchall(cursor)

        paginator = Paginator(range(total_users), ITEMS_PER_PAGE)
        page_obj = paginator.page(page_number)

        return render(request, 'manage_users.html', {
            'users': users,
            'page_obj': page_obj,
            'user_type': user_type
        })

    except Exception as e:
        logger.error(f"Error fetching users: {str(e)}")
        messages.error(request, "Error fetching users. Please try again.")
        return redirect('admin_dashboard')

@login_required
@admin_required
def manage_products(request):
    try:
        page_number = request.GET.get('page', 1)
        
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT p.id, p.proname, p.price, p.currency, p.category, p.created_at,
                       u.username as seller_name
                FROM products p
                JOIN users u ON p.seller_id = u.id
                ORDER BY p.created_at DESC
                LIMIT %s OFFSET %s
            """, [ITEMS_PER_PAGE, (int(page_number) - 1) * ITEMS_PER_PAGE])
            products = dictfetchall(cursor)
            
            cursor.execute("SELECT COUNT(*) as total_products FROM products")
            total_products = dictfetchone(cursor)['total_products']

        paginator = Paginator(range(total_products), ITEMS_PER_PAGE)
        page_obj = paginator.page(page_number)

        return render(request, 'manage_products.html', {
            'products': products,
            'page_obj': page_obj
        })

    except Exception as e:
        logger.error(f"Error fetching products: {str(e)}")
        messages.error(request, "Error fetching products. Please try again.")
        return redirect('admin_dashboard')

@login_required
@admin_required
def manage_orders(request):
    try:
        page_number = request.GET.get('page', 1)
        status = request.GET.get('status', 'all')
        
        base_query = """
            SELECT o.id, o.buyer_id, o.product_id, o.seller_id, o.quantity, o.total_price,
                   o.shipping_address, o.payment_method, o.order_date, o.status,
                   p.proname, u1.username as buyer_name, u2.username as seller_name
            FROM orders o
            JOIN products p ON o.product_id = p.id
            JOIN users u1 ON o.buyer_id = u1.id
            JOIN users u2 ON o.seller_id = u2.id
        """
        
        count_query = "SELECT COUNT(*) as total_orders FROM orders"
        params = []
        
        if status in ['Processing', 'Shipped', 'Delivered', 'Cancelled']:
            base_query += " WHERE o.status = %s"
            count_query += " WHERE status = %s"
            params.append(status)
        
        base_query += " ORDER BY o.order_date DESC LIMIT %s OFFSET %s"
        params.extend([ITEMS_PER_PAGE, (int(page_number) - 1) * ITEMS_PER_PAGE])
        
        with connection.cursor() as cursor:
            cursor.execute(count_query, params[:1] if len(params) > 2 else [])
            total_orders = dictfetchone(cursor)['total_orders']
            
            cursor.execute(base_query, params)
            orders = dictfetchall(cursor)

        paginator = Paginator(range(total_orders), ITEMS_PER_PAGE)
        page_obj = paginator.page(page_number)

        return render(request, 'manage_orders.html', {
            'orders': orders,
            'page_obj': page_obj,
            'status': status
        })

    except Exception as e:
        logger.error(f"Error fetching orders: {str(e)}")
        messages.error(request, "Error fetching orders. Please try again.")
        return redirect('admin_dashboard')

# Common Views
def home(request):
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT p.id, p.proname, p.price, p.prodescription, p.image, 
                   p.created_at, p.seller_id, u.username, p.currency,
                   p.stitch_type
            FROM products p
            JOIN users u ON p.seller_id = u.id
            ORDER BY p.created_at DESC
            LIMIT 6
        """)
        products = dictfetchall(cursor)
    return render(request, 'home.html', {'products': products})

def shop(request):
    query = """
        SELECT p.id, p.proname, p.price, p.prodescription, p.image, p.created_at, 
               p.seller_id, u.username, p.currency, p.category, p.stitch_type
        FROM products p
        JOIN users u ON p.seller_id = u.id
    """
    params = []

    # Filtering
    price_min = request.GET.get('price_min', '')
    price_max = request.GET.get('price_max', '')
    stitch = request.GET.get('stitch', '')
    category = request.GET.get('category', '')
    
    conditions = []
    if price_min:
        conditions.append("p.price >= %s")
        params.append(float(price_min))
    if price_max:
        conditions.append("p.price <= %s")
        params.append(float(price_max))
    if stitch:
        conditions.append("p.stitch_type = %s")
        params.append(stitch)
    if category:
        conditions.append("p.category = %s")
        params.append(category)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    # Sorting
    sort = request.GET.get('sort', 'date_desc')
    if sort == 'price_asc':
        query += " ORDER BY p.price ASC"
    elif sort == 'price_desc':
        query += " ORDER BY p.price DESC"
    else:
        query += " ORDER BY p.created_at DESC"

    with connection.cursor() as cursor:
        cursor.execute(query, params)
        products = dictfetchall(cursor)

    # Pagination
    paginator = Paginator(products, 9)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    return render(request, 'shop.html', {
        'products': page_obj.object_list,
        'page_obj': page_obj,
        'price_min': price_min,
        'price_max': price_max,
        'sort': sort,
        'stitch_filter': stitch,
        'category_filter': category,
        'stitch_types': ['granny', 'amigurumi', 'lace', 'cable', 'tunisian'],
        'categories': ['amigurumi', 'clothing', 'accessories', 'home_decor']
    })

def product_detail(request, product_id):
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT p.id, p.proname, p.price, p.prodescription, p.image, 
                   p.created_at, p.seller_id, u.username, p.currency,
                   p.stitch_type, p.category
            FROM products p
            JOIN users u ON p.seller_id = u.id
            WHERE p.id = %s
        """, [product_id])
        product = dictfetchone(cursor)

    if not product:
        messages.error(request, "Product not found.")
        return redirect('shop')

    # Get reviews
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT r.id, r.rating, r.comment, r.created_at, u.username as buyer_name
            FROM reviews r
            JOIN users u ON r.buyer_id = u.id
            WHERE r.product_id = %s
            ORDER BY r.created_at DESC
        """, [product_id])
        reviews = dictfetchall(cursor)

    # Calculate average rating
    avg_rating = 0
    if reviews:
        avg_rating = sum(review['rating'] for review in reviews) / len(reviews)

    return render(request, 'product_detail.html', {
        'product': product,
        'reviews': reviews,
        'avg_rating': round(avg_rating, 1),
        'star_range': range(1, 6)
    })

@login_required
@buyer_required
def add_review(request, product_id):
    if request.method == 'POST':
        rating = int(request.POST.get('rating', 0))
        comment = request.POST.get('comment', '').strip()
        
        if not (1 <= rating <= 5):
            messages.error(request, "Please select a valid rating (1-5 stars).")
            return redirect('product_detail', product_id=product_id)
        
        try:
            with connection.cursor() as cursor:
                # Verify buyer has purchased the product
                cursor.execute("""
                    SELECT id FROM orders 
                    WHERE buyer_id = %s AND product_id = %s AND status = 'Delivered'
                """, [request.user.id, product_id])
                if not cursor.fetchone():
                    messages.error(request, "You must purchase and receive this product before reviewing.")
                    return redirect('product_detail', product_id=product_id)
                
                # Add review
                cursor.callproc('AddReview', [request.user.id, product_id, rating, comment])
                
                messages.success(request, "Thank you for your review!")
        
        except Exception as e:
            logger.error(f"Error adding review: {str(e)}")
            messages.error(request, "Error submitting your review. Please try again.")
    
    return redirect('product_detail', product_id=product_id)

# Static Pages
def about_us(request):
    return render(request, 'aboutus.html')

def contact(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        message = request.POST.get('message')

        if not all([name, email, message]):
            messages.error(request, "All fields are required.")
            return render(request, 'contact.html')

        try:
            with connection.cursor() as cursor:
                cursor.callproc('AddContact', [name, email, message])
            messages.success(request, "Thank you for your message! We'll get back to you soon.")
        except Exception as e:
            logger.error(f"Error submitting contact form: {str(e)}")
            messages.error(request, "Error submitting your message. Please try again.")
    
    return render(request, 'contact.html')

def faq_list(request):
    with connection.cursor() as cursor:
        cursor.callproc('GetAllFAQs')
        faqs = dictfetchall(cursor)
    
    return render(request, 'faq_list.html', {'faqs': faqs})

def terms_of_service(request):
    return render(request, 'termsofservice.html')

def privacy_policy(request):
    return render(request, 'privacypolicy.html')

def newsletter_subscribe(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        if not email:
            messages.error(request, "Please provide an email address.")
            return redirect('home')

        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO newsletter_subscribers (email, subscribed_at)
                    VALUES (%s, NOW())
                    ON DUPLICATE KEY UPDATE subscribed_at = NOW()
                """, [email])
            
            messages.success(request, "Thank you for subscribing to our newsletter!")
        except Exception as e:
            logger.error(f"Error subscribing to newsletter: {str(e)}")
            messages.error(request, "Error subscribing. Please try again.")
    
    return redirect('home')    

def contact(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        message = request.POST.get('message')

        if not all([name, email, message]):
            messages.error(request, "All fields are required.")
            return render(request, 'contact.html')

        try:
            with connection.cursor() as cursor:
                cursor.callproc('AddContact', [name, email, message])
            messages.success(request, "Thank you for your message! We’ll get back to you soon.")
            return render(request, 'contact.html', {'success': True})
        except Exception as e:
            logger.error(f"Error submitting contact form: {str(e)}")
            messages.error(request, f"Error submitting contact form: {str(e)}")
    return render(request, 'contact.html')

def faq_list(request):
    faqs = []
    try:
        with connection.cursor() as cursor:
            cursor.callproc('GetAllFAQs')
            result = cursor.fetchall()
            for row in result:
                faqs.append({
                    'id': row[0],
                    'question': row[1],
                    'answer': row[2],
                    'created_at': row[3]
                })
    except Exception as e:
        messages.error(request, f"Error fetching FAQs: {str(e)}")

    return render(request, 'faq_list.html', {'faqs': faqs})


from django.views.decorators.csrf import csrf_exempt

@csrf_exempt
def add_faq(request):
    if request.method == 'POST':
        question = request.POST.get('question', '').strip()
        answer = request.POST.get('answer', '').strip()
 
        if question and answer:
            try:
                with connection.cursor() as cursor:
                    cursor.callproc('AddFAQ', [question, answer])
                messages.success(request, "FAQ added successfully!")
                return redirect('faq_list')  # or wherever you list FAQs
            except Exception as e:
                messages.error(request, f"Error adding FAQ: {str(e)}")
        else:
            messages.error(request, "Both question and answer are required.")

    return render(request, 'add_faq.html')


def about_us(request):
    return render(request, 'aboutus.html')

def terms_of_service(request):
    return render(request, 'termsofservice.html')

def privacy_policy(request):
    return render(request, 'privacypolicy.html')


def product_detail(request, product_id):
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT p.id, p.proname, p.price, p.prodescription, p.image, 
                   p.created_at, p.seller_id, u.username, p.currency,
                   p.stitch_type, p.category
            FROM products p
            JOIN users u ON p.seller_id = u.id
            WHERE p.id = %s
        """, [product_id])
        product = dictfetchone(cursor)

    if product:
        return render(request, 'product_detail.html', {'product': product})
    messages.error(request, "Product not found.")
    return redirect('home')


@login_required
def seller_profile(request):
    seller_id = request.session.get('user_id')

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT username, email, first_name, last_name, phone_number, address, profile_picture, bio
            FROM users
            WHERE id = %s
        """, [seller_id])
        seller_data = dictfetchone(cursor)

    if not seller_data:
        messages.error(request, "Seller not found.")
        return redirect('home')

    return render(request, 'seller_profile.html', {
        'user_info': seller_data,
        'username': seller_data.get('username')  # <- important
    })



@login_required
def add_to_wishlist(request):
    # 1) Parse POST form-urlencoded data
    pid = request.POST.get('product_id')
    if not pid:
        return JsonResponse({'success': False, 'message': 'No product ID.'}, status=400)
    try:
        product_id = int(pid)
    except ValueError:
        return JsonResponse({'success': False, 'message': 'Invalid product ID.'}, status=400)

    # 2) Get your custom user id from session
    user_id = request.session.get('user_id')
    if not user_id:
        return JsonResponse({'success': False, 'message': 'Not logged in.'}, status=403)

    # 3) Call the stored procedure
    try:
        with connection.cursor() as cursor:
            cursor.callproc('AddOrRemoveWishlist', [user_id, product_id])
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
    # 4) Return success
    return JsonResponse({'success': True})
def clear_cart(request):
    request.session['cart'] = {}
    request.session.modified = True
    messages.info(request, "Your cart has been cleared.")
    return redirect('shop')

def migrate_cart(request):
    cart = request.session.get('cart', {})
    for product_id, item in cart.items():
        if 'currency' not in item:
            item['currency'] = 'USD'
            with connection.cursor() as cursor:
                cursor.execute("SELECT currency FROM products WHERE id = %s", [product_id])
                result = cursor.fetchone()
                if result:
                    item['currency'] = result[0] or 'USD'
    request.session['cart'] = cart
    request.session.modified = True
    return redirect('view_cart')

def get_exchange_rate(request):
    if 'exchange_rate' in request.session and 'exchange_rate_time' in request.session:
        last_updated = request.session['exchange_rate_time']
        if timezone.now() - last_updated < timedelta(hours=1):
            return request.session['exchange_rate']

    try:
        response = requests.get('https://api.exchangerate-api.com/v4/latest/USD')
        data = response.json()
        rate = data['rates']['INR']
        request.session['exchange_rate'] = rate
        request.session['exchange_rate_time'] = timezone.now()
        return rate
    except Exception:
        return EXCHANGE_RATE_USD_TO_INR

# def newsletter_subscribe(request):
#     if request.method == 'POST':
#         email = request.POST.get('email')
#         if not email:
#             messages.error(request, "Please provide an email address.")
#             return redirect('about_us')

#         try:
#             with connection.cursor() as cursor:
#                 cursor.execute("SELECT COUNT(*) FROM newsletter_subscribers WHERE email = %s", [email])
#                 if cursor.fetchone()[0] > 0:
#                     messages.warning(request, "This email is already subscribed.")
#                     return redirect('about_us')

#                 cursor.execute(
#                     "INSERT INTO newsletter_subscribers (email, subscribed_at, unsubscribe_token) VALUES (%s, NOW(), %s)",
#                     [email, '']
#                 )

#             subject = "Welcome to CroSho’s Newsletter!"
#             message = (
#                 "Dear CroSho Subscriber,\n\n"
#                 "Thank you for joining our crochet community! We're thrilled to have you with us. "
#                 "Expect updates on new patterns, artisan stories, and exclusive offers, all crafted with love.\n\n"
#                 "Happy Stitching,\nThe CroSho Team"
#             )
#             from_email = settings.EMAIL_HOST_USER
#             recipient_list = [email]

#             try:
#                 html_content = render_to_string('emails/newsletter_welcome.html', {})
#                 email = EmailMultiAlternatives(subject, message, from_email, recipient_list)
#                 email.attach_alternative(html_content, "text/html")
#                 email.send()
#                 messages.success(request, "Thank you for subscribing! Check your email for a warm welcome from CroSho.")
#             except Exception as e:
#                 logger.error(f"Failed to send newsletter subscription email to {email}: {str(e)}")
#                 messages.warning(request, "Subscribed successfully, but we couldn’t send the confirmation email. Please contact support.")

#             return redirect('about_us')

#         except Exception as e:
#             logger.error(f"Error subscribing {email} to newsletter: {str(e)}")
#             messages.error(request, "An error occurred while subscribing. Please try again later.")
#             return redirect('about_us')

#     return redirect('about_us')

def patterns(request):
    try:
        with connection.cursor() as cursor:
            cursor.callproc('GetPatterns')
            patterns = dictfetchall(cursor)
        return render(request, 'patterns.html', {'patterns': patterns})
    except Exception as e:
        logger.error(f"Error fetching patterns: {str(e)}")
        return render(request, 'patterns.html', {'error': f"Error fetching patterns: {str(e)}"})

def tutorials(request):
    try:
        with connection.cursor() as cursor:
            cursor.callproc('GetTutorials')
            tutorials = dictfetchall(cursor)
        return render(request, 'tutorials.html', {'tutorials': tutorials})
    except Exception as e:
        logger.error(f"Error fetching tutorials: {str(e)}")
        return render(request, 'tutorials.html', {'error': f"Error fetching tutorials: {str(e)}"})

def yarn_guide(request):
    return render(request, 'yarn_guide.html')

def community(request):
    error = None
    if request.method == 'POST' and 'post_submit' in request.POST:
        title = request.POST.get('title')
        content = request.POST.get('content')
        author = request.user.username if request.user.is_authenticated else 'Anonymous'
        if title and content:
            try:
                with connection.cursor() as cursor:
                    cursor.callproc('InsertCommunityPost', [title, content, author])
            except Exception as e:
                error = f"Error submitting post: {str(e)}"
        else:
            error = "Title and content are required."
        if not error:
            return redirect(request.path)

    if request.method == 'POST' and 'reply_submit' in request.POST:
        post_id = request.POST.get('post_id')
        content = request.POST.get('reply_content')
        author = request.user.username if request.user.is_authenticated else 'Anonymous'
        if post_id and content:
            try:
                with connection.cursor() as cursor:
                    cursor.callproc('InsertPostReply', [post_id, content, author])
            except Exception as e:
                error = f"Error submitting reply: {str(e)}"
        else:
            error = "Reply content and post ID are required."
        if not error:
            return redirect(request.path)

    try:
        with connection.cursor() as cursor:
            cursor.callproc('GetCommunityPosts')
            posts = dictfetchall(cursor)
            for post in posts:
                cursor.execute("SELECT id, post_id, content, author, created_at FROM post_replies WHERE post_id = %s", [post['id']])
                post['replies'] = dictfetchall(cursor)
    except Exception as e:
        logger.error(f"Error fetching posts: {str(e)}")
        return render(request, 'community.html', {'error': f"Error fetching posts: {str(e)}"})

    return render(request, 'community.html', {'posts': posts, 'error': error})

@login_required
def edit_profile(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, username, email, first_name, last_name, phone_number, address,
                       profile_picture, bio, user_type, created_at
                FROM users
                WHERE id = %s
            """, [request.user.id])
            user_info = dictfetchone(cursor)
    except Exception as e:
        logger.error(f"Error fetching user data: {str(e)}")
        user_info = {}
        messages.error(request, f"Error fetching profile: {str(e)}")

    if request.method == 'POST':
        try:
            username = request.POST.get('username')
            email = request.POST.get('email')
            first_name = request.POST.get('first_name', '')
            last_name = request.POST.get('last_name', '')
            phone_number = request.POST.get('phone_number', '')
            address = request.POST.get('address', '')
            bio = request.POST.get('bio', '')
            profile_picture = request.FILES.get('profile_picture')
            password = request.POST.get('password', '')  # Optional password update

            # Validate inputs
            if User.objects.filter(username=username).exclude(id=request.user.id).exists():
                messages.error(request, "Username already exists.")
                return render(request, 'edit_profile.html', {'user_info': user_info})
            if User.objects.filter(email=email).exclude(id=request.user.id).exists():
                messages.error(request, "Email already exists.")
                return render(request, 'edit_profile.html', {'user_info': user_info})

            # Update auth_user
            request.user.username = username
            request.user.email = email
            request.user.first_name = first_name
            request.user.last_name = last_name
            if password:
                request.user.set_password(password)
            request.user.save()

            # Handle file upload
            profile_picture_path = user_info.get('profile_picture')
            if profile_picture:
                mime_type, _ = mimetypes.guess_type(profile_picture.name)
                if not mime_type or not mime_type.startswith('image'):
                    messages.error(request, "Profile picture must be an image.")
                    return render(request, 'edit_profile.html', {'user_info': user_info})
                if profile_picture.size > 5 * 1024 * 1024:  # 5MB limit
                    messages.error(request, "Profile picture must be less than 5MB.")
                    return render(request, 'edit_profile.html', {'user_info': user_info})
                fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'profiles'))
                filename = fs.save(profile_picture.name, profile_picture)
                profile_picture_path = f"profiles/{filename}"
                if user_info.get('profile_picture'):
                    fs.delete(user_info['profile_picture'])

            # Update users table
            with connection.cursor() as cursor:
                cursor.callproc('ManageUserProfile', [
                    request.user.id, username, email, password or user_info.get('userspassword', ''),
                    first_name, last_name, phone_number, address, profile_picture_path, bio,
                    request.session['user_type']
                ])

            messages.success(request, "Profile updated successfully!")
            return redirect('seller_profile' if request.session['user_type'] == 'seller' else 'buyer_profile')

        except Exception as e:
            logger.error(f"Error in edit_profile view: {str(e)}")
            messages.error(request, f"Error updating profile: {str(e)}")
            return render(request, 'edit_profile.html', {'user_info': user_info})

    return render(request, 'edit_profile.html', {'user_info': user_info})





# ! updated views.........

from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.conf import settings
import os
from decimal import Decimal
import uuid
import logging

logger = logging.getLogger(__name__)

# Helper function to get cart from session or database
def get_user_cart(request):
    cart = {}
    
    # For authenticated users - check database first
    if request.user.is_authenticated and request.session.get('user_type') == 'buyer':
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT product_id, quantity FROM user_carts 
                WHERE user_id = %s
            """, [request.user.id])
            db_cart = dictfetchall(cursor)
            
            for item in db_cart:
                cart[str(item['product_id'])] = {'quantity': item['quantity']}
    
    # Merge with session cart if exists
    session_cart = request.session.get('cart', {})
    for product_id, item in session_cart.items():
        if product_id in cart:
            cart[product_id]['quantity'] += item['quantity']
        else:
            cart[product_id] = item
    
    return cart

# Helper function to save cart to both session and database
def save_user_cart(request, cart):
    # Always save to session
    request.session['cart'] = cart
    request.session.modified = True
    
    # For authenticated buyers, save to database
    if request.user.is_authenticated and request.session.get('user_type') == 'buyer':
        with connection.cursor() as cursor:
            # First clear existing cart items
            cursor.execute("DELETE FROM user_carts WHERE user_id = %s", [request.user.id])
            
            # Insert current cart items
            for product_id, item in cart.items():
                cursor.execute("""
                    INSERT INTO user_carts (user_id, product_id, quantity)
                    VALUES (%s, %s, %s)
                """, [request.user.id, product_id, item['quantity']])

@login_required
def update_profile(request):
    if request.method == 'POST':
        bio = request.POST.get('bio', '').strip()
        address = request.POST.get('address', '').strip()
        phone_number = request.POST.get('phone_number', '').strip()
        profile_picture = request.FILES.get('profile_picture')

        profile_picture_path = None

        if profile_picture:
            if profile_picture.size > 5 * 1024 * 1024:
                messages.error(request, "Profile picture must be under 5MB.")
                return redirect('update_profile')
            if not profile_picture.content_type.startswith('image/'):
                messages.error(request, "Invalid file type for profile picture.")
                return redirect('update_profile')

            fs = FileSystemStorage(location=os.path.join(settings.MEDIA_ROOT, 'profiles'))
            filename = fs.save(profile_picture.name, profile_picture)
            profile_picture_path = os.path.join('profiles', filename)

        try:
            with connection.cursor() as cursor:
                cursor.callproc('UpdateUserProfile', [
                    request.user.id,
                    bio,
                    address,
                    phone_number,
                    profile_picture_path
                ])

            messages.success(request, "Profile updated successfully!")
            return redirect('buyer_profile' if request.session.get('user_type') == 'buyer' else 'seller_profile')

        except Exception as e:
            logger.error(f"Error updating profile: {str(e)}")
            messages.error(request, "Failed to update profile.")
            if profile_picture_path:
                fs.delete(filename)

    # GET request - fetch existing profile
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT bio, address, phone_number, profile_picture
            FROM user_profiles
            WHERE user_id = %s
        """, [request.user.id])
        profile = dictfetchall(cursor)

    return render(request, 'update_profile.html', {'profile': profile[0] if profile else None})



#!!!!!!!! Blog Posts

from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import connection
from django.shortcuts import render, get_object_or_404

def _dictfetchall(cursor):
    cols = [c[0] for c in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]

def _dictfetchone(cursor):
    row = cursor.fetchone()
    return dict(zip([c[0] for c in cursor.description], row)) if row else None

def _callproc(cursor, proc_name, params=None):
    cursor.callproc(proc_name, params or [])
    # advance to first real result set
    while cursor.description is None and cursor.nextset():
        pass

@login_required
def blog(request):
    # Featured post
    with connection.cursor() as cursor:
        _callproc(cursor, 'GetFeaturedBlogPost')
        featured_post = _dictfetchone(cursor)

    # Page number (safe int conversion)
    try:
        page_number = int(request.GET.get('page', 1))
        if page_number < 1:
            raise ValueError
    except ValueError:
        page_number = 1

    # Paginated posts + total count
    with connection.cursor() as cursor:
        _callproc(cursor, 'GetPaginatedBlogPosts', [page_number, 6])
        blog_posts = _dictfetchall(cursor)
        while cursor.nextset():  # clear any extra result sets
            pass

    with connection.cursor() as cursor:
        _callproc(cursor, 'GetTotalBlogPostsCount')
        total_posts = _dictfetchone(cursor)['total_posts'] or 0

    paginator = Paginator(blog_posts, 6)
    try:
        page_obj = paginator.page(page_number)
    except (EmptyPage, PageNotAnInteger):
        page_obj = paginator.page(1)

    # Categories + popular posts
    with connection.cursor() as cursor:
        _callproc(cursor, 'GetBlogCategories')
        categories = _dictfetchall(cursor)
    with connection.cursor() as cursor:
        _callproc(cursor, 'GetPopularBlogPosts', [5])
        popular_posts = _dictfetchall(cursor)

    return render(request, 'blog.html', {
        'featured_post': featured_post,
        'page_obj':       page_obj,
        'categories':     categories,
        'popular_posts':  popular_posts,
        'total_posts':    total_posts,
    })
    
from django.http import Http404    

@login_required
def blog_post(request, featured_post_id):
    # Fetch single blog post
    with connection.cursor() as cursor:
        _callproc(cursor, 'GetBlogPostById', [featured_post_id])
        post = _dictfetchone(cursor)
    if not post:
        raise Http404("Blog post not found.")

    # Fetch associated comments 
    with connection.cursor() as cursor:
        _callproc(cursor, 'GetBlogPostComments', [featured_post_id])
        comments = _dictfetchall(cursor)

    return render(request, 'blog_post.html', {
        'post': post,
        'comments': comments,
    })




# import logging
# from decimal import Decimal
# from django.http import JsonResponse
# from django.shortcuts import render, redirect
# from django.contrib import messages
# from django.db import connection
# from django.contrib.auth.decorators import login_required

# logger = logging.getLogger(__name__)

# def dictfetchone(cursor):
#     columns = [col[0] for col in cursor.description]
#     return dict(zip(columns, cursor.fetchone())) if cursor.rowcount else None

# def dictfetchall(cursor):
#     columns = [col[0] for col in cursor.description]
#     return [dict(zip(columns, row)) for row in cursor.fetchall()]

# @login_required
# def add_to_cart(request, product_id):
#     if request.session.get('user_type') != 'buyer':
#         messages.error(request, "Please log in as a buyer to add to cart.")
#         return redirect('login')

#     # Fetch product details
#     with connection.cursor() as cursor:
#         cursor.execute("""
#             SELECT p.id, p.proname, p.price, p.prodescription, p.image, p.created_at, 
#                    p.seller_id, u.username, p.currency
#             FROM products p
#             JOIN users u ON p.seller_id = u.id
#             WHERE p.id = %s
#         """, [product_id])
#         product = dictfetchone(cursor)

#     if not product:
#         if request.headers.get('x-requested-with') == 'XMLHttpRequest':
#             return JsonResponse({'success': False, 'message': 'Product not found.'}, status=404)
#         messages.error(request, "Product not found.")
#         return redirect('shop')

#     # Get quantity
#     quantity = int(request.POST.get('quantity', 1)) if request.method == 'POST' else 1
#     if quantity < 1:
#         if request.headers.get('x-requested-with') == 'XMLHttpRequest':
#             return JsonResponse({'success': False, 'message': 'Quantity must be at least 1.'}, status=400)
#         messages.error(request, "Quantity must be at least 1.")
#         return redirect('shop')

#     # Add to cart using stored procedure
#     try:
#         with connection.cursor() as cursor:
#             cursor.callproc('AddToCart', [request.user.id, product_id, quantity])
#     except Exception as e:
#         logger.error(f"Error adding to cart: {str(e)}")
#         if request.headers.get('x-requested-with') == 'XMLHttpRequest':
#             return JsonResponse({'success': False, 'message': str(e)}, status=500)
#         messages.error(request, f"Error adding to cart: {str(e)}")
#         return redirect('shop')

#     # Get recommended products
#     lower_price = product['price'] * Decimal('0.8')
#     upper_price = product['price'] * Decimal('1.2')
#     with connection.cursor() as cursor:
#         cursor.execute("""
#             SELECT p.id, p.proname, p.price, p.prodescription, p.image, p.created_at, 
#                    p.seller_id, u.username, p.currency
#             FROM products p
#             JOIN users u ON p.seller_id = u.id
#             WHERE (p.seller_id = %s OR p.price BETWEEN %s AND %s) AND p.id != %s
#             ORDER BY p.created_at DESC
#             LIMIT 3
#         """, [product['seller_id'], lower_price, upper_price, product_id])
#         recommended_products = dictfetchall(cursor)

#     # Handle response
#     if request.headers.get('x-requested-with') == 'XMLHttpRequest':
#         return JsonResponse({
#             'success': True,
#             'message': f"{product['proname']} added to your cart!",
#             'product': {
#                 'id': product['id'],
#                 'name': product['proname'],
#                 'price': float(product['price']),
#                 'currency': product['currency']
#             }
#         })
    
#     messages.success(request, f"{product['proname']} added to your cart!")
#     return render(request, 'cart_added.html', {
#         'product': product,
#         'recommended_products': recommended_products
#     })


# def view_cart(request):
#     cart = get_user_cart(request)
#     cart_items = []
#     total_price = {'USD': 0.0, 'INR': 0.0}

#     # Get full product details for items in cart
#     if cart:
#         product_ids = list(cart.keys())
#         placeholders = ','.join(['%s'] * len(product_ids))
        
#         with connection.cursor() as cursor:
#             cursor.execute(f"""
#                 SELECT p.id, p.proname, p.price, p.image, p.currency, u.username as seller
#                 FROM products p
#                 JOIN users u ON p.seller_id = u.id
#                 WHERE p.id IN ({placeholders})
#             """, product_ids)
#             products = {str(item['id']): item for item in dictfetchall(cursor)}
        
#         for product_id, item in cart.items():
#             if product_id in products:
#                 product = products[product_id]
#                 currency = product.get('currency', 'USD')
#                 subtotal = product['price'] * item['quantity']
                
#                 cart_items.append({
#                     'product_id': product_id,
#                     'name': product['proname'],
#                     'price': product['price'],
#                     'quantity': item['quantity'],
#                     'image': product['image'],
#                     'subtotal': subtotal,
#                     'seller': product['seller'],
#                     'seller_id': product.get('seller_id'),
#                     'currency': currency
#                 })
                
#                 if currency == 'USD':
#                     total_price['USD'] += subtotal
#                 else:
#                     total_price['INR'] += subtotal

#     return render(request, 'cart.html', {
#         'cart_items': cart_items,
#         'total_price': total_price,
#         'is_anonymous': not request.user.is_authenticated
#     })

# def update_cart(request, product_id):
#     if request.method == 'POST':
#         quantity = int(request.POST.get('quantity', 1))
#         cart = get_user_cart(request)
#         product_id_str = str(product_id)

#         if product_id_str in cart:
#             if quantity <= 0:
#                 del cart[product_id_str]
#             else:
#                 cart[product_id_str]['quantity'] = quantity
            
#             save_user_cart(request, cart)

#     return redirect('view_cart')

# def remove_from_cart(request, product_id):
#     cart = get_user_cart(request)
#     product_id_str = str(product_id)

#     if product_id_str in cart:
#         del cart[product_id_str]
#         save_user_cart(request, cart)

#     return redirect('view_cart')


# # Constants
# EXCHANGE_RATE_USD_TO_INR = 83.0
# ITEMS_PER_PAGE = 10

# @login_required
# def seller_orders(request):
#     """View to display and manage seller orders"""
#     if request.session.get('user_type') != 'seller':
#         messages.error(request, "You are not authorized to view this page.")
#         return redirect('home')

#     # Handle status update form submission
#     if request.method == 'POST' and 'update_status' in request.POST:
#         return update_order_status(request)

#     # Get paginated orders
#     page_number = request.GET.get('page', 1)
    
#     try:
#         with connection.cursor() as cursor:
#             # Get orders for this seller
#             cursor.execute("""
#                 SELECT o.id, o.buyer_id, o.product_id, o.seller_id, o.quantity, 
#                        o.total_price, o.shipping_address, o.payment_method, 
#                        o.order_date, o.status, o.shipped_date, o.delivered_date,
#                        p.proname, p.currency,
#                        CASE WHEN p.currency = 'USD' THEN o.total_price * %s ELSE o.total_price END AS total_price_inr,
#                        u.username as buyer_username
#                 FROM orders o
#                 JOIN products p ON o.product_id = p.id
#                 JOIN users u ON o.buyer_id = u.id
#                 WHERE o.seller_id = %s
#                 ORDER BY o.order_date DESC
#                 LIMIT %s OFFSET %s
#             """, [
#                 EXCHANGE_RATE_USD_TO_INR,
#                 request.session.get('user_id'),
#                 ITEMS_PER_PAGE,
#                 (int(page_number) - 1) * ITEMS_PER_PAGE
#             ])
#             orders = dictfetchall(cursor)

#             # Get total count for pagination
#             cursor.execute("""
#                 SELECT COUNT(*) as total_orders
#                 FROM orders
#                 WHERE seller_id = %s
#             """, [request.session.get('user_id')])
#             total_orders = dictfetchone(cursor)['total_orders']

#         paginator = Paginator(range(total_orders), ITEMS_PER_PAGE)
#         page_obj = paginator.page(page_number)

#         return render(request, 'seller_orders.html', {
#             'orders': orders,
#             'page_obj': page_obj,
#             'status_choices': ['Processing', 'Shipped', 'Delivered', 'Cancelled']
#         })

#     except Exception as e:
#         logger.error(f"Error fetching seller orders: {str(e)}")
#         messages.error(request, "Error fetching your orders. Please try again later.")
#         return redirect('seller_dashboard')

# def update_order_status(request):
#     """Handle order status updates"""
#     order_id = request.POST.get('order_id')
#     new_status = request.POST.get('new_status')
#     valid_statuses = ['Processing', 'Shipped', 'Delivered', 'Cancelled']

#     if not order_id or not new_status or new_status not in valid_statuses:
#         messages.error(request, "Invalid status update request.")
#         return redirect('seller_orders')

#     try:
#         with connection.cursor() as cursor:
#             # Verify order belongs to this seller
#             cursor.execute("""
#                 SELECT seller_id FROM orders WHERE id = %s
#             """, [order_id])
#             order = dictfetchone(cursor)

#             if not order or order['seller_id'] != request.session.get('user_id'):
#                 messages.error(request, "Order not found or unauthorized.")
#                 return redirect('seller_orders')

#             # Update status with appropriate timestamps
#             update_query = "UPDATE orders SET status = %s"
#             params = [new_status]

#             if new_status == 'Shipped':
#                 update_query += ", shipped_date = NOW()"
#             elif new_status == 'Delivered':
#                 update_query += ", delivered_date = NOW()"
#             elif new_status == 'Cancelled':
#                 update_query += ", cancelled_date = NOW()"

#             update_query += " WHERE id = %s"
#             params.append(order_id)

#             cursor.execute(update_query, params)
#             messages.success(request, f"Order #{order_id} status updated to {new_status}")

#     except Exception as e:
#         logger.error(f"Error updating order status: {str(e)}")
#         messages.error(request, f"Error updating order status: {str(e)}")

#     return redirect('seller_orders')

# # Utility functions
# def dictfetchall(cursor):
#     """Return all rows from a cursor as a dict"""
#     columns = [col[0] for col in cursor.description]
#     return [dict(zip(columns, row)) for row in cursor.fetchall()]

# def dictfetchone(cursor):
#     """Return single row from cursor as a dict"""
#     columns = [col[0] for col in cursor.description]
#     row = cursor.fetchone()
#     return dict(zip(columns, row)) if row else None


# @login_required
# def seller_reviews(request):
#     """View to display reviews for the seller's products"""
#     if request.session.get('user_type') != 'seller':
#         messages.error(request, "You are not authorized to view this page.")
#         return redirect('home')

#     page_number = request.GET.get('page', 1)
#     items_per_page = 10

#     try:
#         with connection.cursor() as cursor:
#             # Get paginated reviews
#             cursor.execute("""
#                 SELECT r.id, r.product_id, r.buyer_id, r.rating, r.comment, 
#                        r.created_at, p.proname, u.username as buyer_name
#                 FROM reviews r
#                 JOIN products p ON r.product_id = p.id
#                 JOIN users u ON r.buyer_id = u.id
#                 WHERE p.seller_id = %s
#                 ORDER BY r.created_at DESC
#                 LIMIT %s OFFSET %s
#             """, [request.session.get('user_id'), items_per_page, (int(page_number) - 1) * items_per_page])
#             reviews = dictfetchall(cursor)

#             # Get total count for pagination
#             cursor.execute("""
#                 SELECT COUNT(*) as total_reviews
#                 FROM reviews r
#                 JOIN products p ON r.product_id = p.id
#                 WHERE p.seller_id = %s
#             """, [request.session.get('user_id')])
#             total_reviews = dictfetchone(cursor)['total_reviews']

#             # Get average rating
#             cursor.execute("""
#                 SELECT AVG(r.rating) as avg_rating, COUNT(r.id) as review_count
#                 FROM reviews r
#                 JOIN products p ON r.product_id = p.id
#                 WHERE p.seller_id = %s
#             """, [request.session.get('user_id')])
#             rating_stats = dictfetchone(cursor)

#         paginator = Paginator(range(total_reviews), items_per_page)
#         page_obj = paginator.page(page_number)

#         return render(request, 'seller_reviews.html', {
#             'reviews': reviews,
#             'page_obj': page_obj,
#             'rating_stats': rating_stats,
#             'star_range': range(1, 6)
#         })

#     except Exception as e:
#         logger.error(f"Error fetching seller reviews: {str(e)}")
#         messages.error(request, "Error fetching your reviews. Please try again later.")
#         return redirect('seller_dashboard')

# @login_required
# def reply_to_review(request, review_id):
#     """Handle seller replies to reviews"""
#     if request.session.get('user_type') != 'seller':
#         messages.error(request, "You are not authorized to reply to reviews.")
#         return redirect('home')

#     if request.method == 'POST':
#         reply_text = request.POST.get('reply_text', '').strip()

#         try:
#             with connection.cursor() as cursor:
#                 # Verify the review is for the seller's product
#                 cursor.execute("""
#                     SELECT p.seller_id 
#                     FROM reviews r
#                     JOIN products p ON r.product_id = p.id
#                     WHERE r.id = %s
#                 """, [review_id])
#                 result = dictfetchone(cursor)

#                 if not result or result['seller_id'] != request.session.get('user_id'):
#                     messages.error(request, "Review not found or unauthorized.")
#                     return redirect('seller_reviews')

#                 # Update the review with seller's reply
#                 cursor.execute("""
#                     UPDATE reviews 
#                     SET seller_reply = %s, reply_date = NOW()
#                     WHERE id = %s
#                 """, [reply_text, review_id])

#                 messages.success(request, "Your reply has been added to the review.")
#                 return redirect('seller_reviews')

#         except Exception as e:
#             logger.error(f"Error replying to review: {str(e)}")
#             messages.error(request, "Error saving your reply. Please try again.")

#     return redirect('seller_reviews')