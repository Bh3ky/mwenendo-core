# Learnings

- `render()` locates an HTML template, combines it with the context data and returns an HTTP response.
- `JsonResponse()` serialises Python data into JSON and returns an HTTP response with the appropriate content type. 

**pytest**

- `client` is a pytest-django fixture, a fake HTTP client that calls your views without starting a server. pytest injects it because the parameter name matches.