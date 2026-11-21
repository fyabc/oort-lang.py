local function loop_sum(n)
    local total = 0
    for i = 0, n - 1 do
        total = total + i
    end
    return total
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

local result, elapsed_ms = measure(function() return loop_sum(20000) end)
print(result)
print(elapsed_ms)
