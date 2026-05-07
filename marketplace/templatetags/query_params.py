from django import template

register = template.Library()

@register.simple_tag
def url_replace(request, field, value):
    """
    Takes the current request, copies the GET parameters, 
    replaces/adds the specific field, and returns an encoded string.
    """
    dict_copy = request.GET.copy()
    dict_copy[field] = value
    return dict_copy.urlencode()