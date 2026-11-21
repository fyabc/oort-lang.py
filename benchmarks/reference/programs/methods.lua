local Counter = {}
Counter.__index = Counter

function Counter.new()
    return setmetatable({ value = 0 }, Counter)
end

function Counter:bump()
    self.value = self.value + 1
end

local function run(n)
    local counter = Counter.new()
    for _ = 1, n do
        counter:bump()
    end
    return counter.value
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

local result, elapsed_ms = measure(function() return run(5000) end)
print(result)
print(elapsed_ms)
