from http import HTTPStatus

from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None

    original_data = response.data
    code = _get_error_code(exc, response.status_code)
    message = _get_error_message(original_data, response.status_code)

    if isinstance(original_data, dict):
        response.data = dict(original_data)
    else:
        response.data = {"detail": original_data}

    response.data.setdefault(
        "error",
        {
            "status": response.status_code,
            "code": code,
            "message": message,
            "details": original_data,
        },
    )
    return response


def _get_error_code(exc, status_code: int) -> str:
    codes = exc.get_codes() if hasattr(exc, "get_codes") else None
    if isinstance(codes, str):
        return codes
    if isinstance(codes, dict):
        detail_code = codes.get("code") or codes.get("detail")
        if isinstance(detail_code, str):
            return detail_code
    if status_code == 400:
        return "validation_error"
    return HTTPStatus(status_code).phrase.lower().replace(" ", "_")


def _get_error_message(data, status_code: int) -> str:
    if isinstance(data, dict):
        detail = data.get("detail")
        if isinstance(detail, str):
            return detail
    return HTTPStatus(status_code).phrase
