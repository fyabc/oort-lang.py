import time


def loop_sum(n):
    total = 0
    i = 0
    while i < n:
        total += i
        i += 1
    return total


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


result, elapsed_ms = measure(lambda: loop_sum(20_000))
print(result)
print(elapsed_ms)
