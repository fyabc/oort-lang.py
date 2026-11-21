import time


def fib(n):
    if n <= 1:
        return n
    return fib(n - 1) + fib(n - 2)


def measure(fn):
    fn()
    start = time.perf_counter()
    reps = 0
    result = None
    while reps < 100_000:
        result = fn()
        reps += 1
        if (time.perf_counter() - start) * 1000 >= 100:
            break
    return result, (time.perf_counter() - start) * 1000 / reps


result, elapsed_ms = measure(lambda: fib(20))
print(result)
print(elapsed_ms)
