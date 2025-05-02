from django.db import connection

def cart_context(request):
    cart_items = []
    cart_count = 0
    try:
        user = request.user
        user_type = request.session.get('user_type')

        if user.is_authenticated and (user.is_staff or user_type == 'buyer'):
            with connection.cursor() as cursor:
                cursor.callproc('GetUserCart', [user.id])
                while cursor.description is None:
                    cursor.nextset()
                if cursor.description:
                    columns = [col[0] for col in cursor.description]
                    cart_items = [dict(zip(columns, row)) for row in cursor.fetchall()]
                    cart_count = len(cart_items)
    except Exception as e:
        cart_items = []
        cart_count = 0

    return {
        'cart_items': cart_items,
        'cart_count': cart_count
    }
