import time


class Counter:
    def __init__(self):
        self.value = 0

    def bump(self):
        self.value += 1


def run(n):
    counter = Counter()
    for _ in range(n):
        counter.bump()
    return counter.value


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


result, elapsed_ms = measure(lambda: run(5_000))
print(result)
print(elapsed_ms)
