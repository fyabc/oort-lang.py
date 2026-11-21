local function fib(n)
    if n <= 1 then return n end
    return fib(n - 1) + fib(n - 2)
end

local function measure(fn)
    fn()
    local start = os.clock()
    local reps = 0
    local result
    while reps < 100000 do
        result = fn()
        reps = reps + 1
        if (os.clock() - start) * 1000 >= 100 then break end
    end
    return result, (os.clock() - start) * 1000 / reps
end

local result, elapsed_ms = measure(function() return fib(20) end)
print(result)
print(elapsed_ms)
