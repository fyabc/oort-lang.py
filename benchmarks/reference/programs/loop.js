const { performance } = require("node:perf_hooks");

function loopSum(n) {
    let total = 0;
    for (let i = 0; i < n; i += 1) {
        total += i;
    }
    return total;
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

const [result, elapsedMs] = measure(() => loopSum(20000));
console.log(result);
console.log(elapsedMs);
