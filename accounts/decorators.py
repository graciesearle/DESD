from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.contrib import messages

def _role_required(*roles, redirect_url=None, message=None):

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def _wrapped(request, *args, **kwargs):
            if request.user.role in roles:
                return view_func(request, *args, **kwargs)

            if redirect_url:
                msg = message or "You do not have permission to access that page."
                messages.error(request, msg)
                return redirect(redirect_url)

            raise PermissionDenied 

        return _wrapped
    return decorator


# Public decorators

def producer_required(view_func=None, *, redirect_url=None,
                      message="Only producer accounts can access this page."):
    decorator = _role_required("PRODUCER", redirect_url=redirect_url, message=message)
    if view_func is not None:
        return decorator(view_func)
    return decorator


def customer_required(view_func=None, *, redirect_url=None,
                      message="Only customer accounts can access this page."):
    decorator = _role_required(
        "CUSTOMER", "COMMUNITY_GROUP", "RESTAURANT",
        redirect_url=redirect_url,
        message=message,
    )
    if view_func is not None:
        return decorator(view_func)
    return decorator


def admin_required(view_func=None, *, redirect_url=None,
                   message="Administrator access is required."):
    decorator = _role_required("ADMIN", redirect_url=redirect_url, message=message)
    if view_func is not None:
        return decorator(view_func)
    return decorator


def community_group_required(view_func=None, *, redirect_url=None,
                              message="This feature is for community group accounts."):
    decorator = _role_required("COMMUNITY_GROUP", redirect_url=redirect_url, message=message)
    if view_func is not None:
        return decorator(view_func)
    return decorator


def restaurant_required(view_func=None, *, redirect_url=None,
                        message="This feature is for restaurant / café accounts."):
    decorator = _role_required("RESTAURANT", redirect_url=redirect_url, message=message)
    if view_func is not None:
        return decorator(view_func)
    return decorator


def producer_or_admin_required(view_func=None, *, redirect_url=None,
                                message="Producer or administrator access required."):
    decorator = _role_required("PRODUCER", "ADMIN", redirect_url=redirect_url, message=message)
    if view_func is not None:
        return decorator(view_func)
    return decorator
