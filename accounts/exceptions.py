from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    """Return one predictable error shape for DRF API clients."""
    response = exception_handler(exc, context)
    if response is None:
        return response

    data = response.data
    if isinstance(data, dict) and "detail" in data and len(data) == 1:
        message = str(data["detail"])
        fields = None
    else:
        message = "Request validation failed."
        fields = data

    error = {"code": _error_code(response.status_code, exc), "message": message}
    if fields is not None:
        error["fields"] = fields
    response.data = {"error": error}
    return response


def _error_code(status_code, exc=None):
    if getattr(exc, "default_code", None) == "plan_limit_exceeded":
        return "plan_limit_exceeded"
    return {
        400: "validation_error",
        401: "authentication_required",
        403: "permission_denied",
        404: "not_found",
        405: "method_not_allowed",
        429: "rate_limited",
        503: "service_unavailable",
    }.get(status_code, "api_error")
