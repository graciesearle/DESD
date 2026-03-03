from django.shortcuts import render

# Create your views here.
from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib import messages

from .forms import ProducerRegistrationForm, CustomerRegistrationForm

import requests
from django.http import JsonResponse
from django.conf import settings

def producer_register(request):
    if request.method == "POST":
        form = ProducerRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Your producer account has been created successfully.")
            return redirect("producer_dashboard")
    else:
        form = ProducerRegistrationForm()

    return render(request, "accounts/producer_register.html", {"form": form})


def customer_register(request):
    if request.method == "POST":
        form = CustomerRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Your customer account has been created successfully.")
            return redirect("customer_dashboard")
    else:
        form = CustomerRegistrationForm()

    return render(request, "accounts/customer_register.html", {"form": form})


#address lookup
"""def address_search(request):
    query = request.GET.get("q")

    if not query:
        return JsonResponse({"results": []})

    try:
        response = requests.get(
            "https://portal.goaddress.io/api/address/search",
            params={"q": query},
            headers={"Authorization": f"Bearer {settings.GO_ADDRESS_TOKEN}"},
            timeout=5
        )

        # temporary
        print("STATUS:", response.status_code)
        print("BODY:", response.text)
        print("TOKEN:", settings.GO_ADDRESS_TOKEN)

        if response.status_code != 200:
            return JsonResponse(
                {"error": "Address lookup failed"},
                status=response.status_code
            )
        return JsonResponse(response.json())

    except requests.RequestException as e:
        print("ERROR in address_search:", e)
        return JsonResponse({"error": str(e)}, status=500)"""
def address_search(request):
    q = request.GET.get('q')
    if not q:
        return JsonResponse({"error": "No postcode provided"}, status=400)

    url = f"https://portal.goaddress.io/api/address/search"
    headers = {"Authorization": f"Bearer {settings.GO_ADDRESS_TOKEN}",
                "Accept": "application/json"}
    params = {"q": q}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()  # Raise exception for HTTP errors
        data = response.json()
        return JsonResponse(data)

    except requests.RequestException as e:
        print("GO_ADDRESS_TOKEN:", settings.GO_ADDRESS_TOKEN)
        print("API response status:", response.status_code)
        print("API raw text:", response.text)
        print("RequestException:", e)
        return JsonResponse({"error": str(e)}, status=500)
    except ValueError as ve:
        print("JSON decode error:", ve)
        return JsonResponse({"error": "Invalid JSON from GoAddress"}, status=502)