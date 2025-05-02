from django import template

register = template.Library()


@register.filter
def subtract(value, arg):
    return float(value) - float(arg)
@register.filter
def multiply(value, arg):
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return ''

@register.filter
def divide(value, arg):
    try:
        return round(float(value) / float(arg), 2)
    except (ValueError, ZeroDivisionError):
        return None