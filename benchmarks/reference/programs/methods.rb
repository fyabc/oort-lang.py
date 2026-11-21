class Counter
  attr_reader :value

  def initialize
    @value = 0
  end

  def bump
    @value += 1
  end
end

def run(n)
  counter = Counter.new
  n.times { counter.bump }
  counter.value
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

result, elapsed_ms = measure { run(5_000) }
puts result
puts elapsed_ms
