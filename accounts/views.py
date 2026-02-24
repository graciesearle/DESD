from django.shortcuts import render

# Create your views here.
def producer_register(request):
    return render(request, "accounts/producer_register.html")

def customer_register(request):
    return render(request, "accounts/customer_register.html")
