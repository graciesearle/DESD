from django import template

register = template.Library()

#i got an error when i tries to add class the same way i did pre model creation so this is to go around it and fix the issue
@register.filter
def add_class(field, css):
    return field.as_widget(attrs={"class": css})
