from func_timeout import func_timeout, FunctionTimedOut


def run_function_timeout(function, timeout, *args, **kwargs):
    try:
        return_value = func_timeout(timeout, function, args=args, kwargs=kwargs)
    except FunctionTimedOut:
        return_value = None
    return return_value