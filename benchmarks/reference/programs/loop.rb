def loop_sum(n)
  total = 0
  i = 0
  while i < n
    total += i
    i += 1
  end
  total
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

result, elapsed_ms = measure { loop_sum(20_000) }
puts result
puts elapsed_ms
