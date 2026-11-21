def fib(n)
  return n if n <= 1

  fib(n - 1) + fib(n - 2)
end

def measure
  yield
  start = Process.clock_gettime(Process::CLOCK_MONOTONIC)
  reps = 0
  result = nil
  while reps < 100_000
    result = yield
    reps += 1
    break if (Process.clock_gettime(Process::CLOCK_MONOTONIC) - start) * 1000 >= 100
  end
  [result, (Process.clock_gettime(Process::CLOCK_MONOTONIC) - start) * 1000 / reps]
end

result, elapsed_ms = measure { fib(20) }
puts result
puts elapsed_ms
