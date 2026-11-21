const { performance } = require("node:perf_hooks");

function fib(n) {
    if (n <= 1) return n;
    return fib(n - 1) + fib(n - 2);
}

function measure(fn) {
    fn();
    const start = performance.now();
    let reps = 0;
    let result = 0;
    while (reps < 100000) {
        result = fn();
        reps += 1;
        if (performance.now() - start >= 100) break;
    }
    return [result, (performance.now() - start) / reps];
}

const [result, elapsedMs] = measure(() => fib(20));
console.log(result);
console.log(elapsedMs);
