from django.shortcuts import render

def fetcher(request):
  return render(request, 'fetcher/home.html')