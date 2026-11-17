from django.http import JsonResponse
from django.shortcuts import render


def home(request):
    context = {
        "project_name": "Mwenendo Core",
        "description": "Inventory allocation and reservation engine",
    }

    return render(request, "core/home.html", context)


def health_check(request):
    return JsonResponse({"status": "healthy"})
