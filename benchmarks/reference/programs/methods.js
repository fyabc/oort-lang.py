const { performance } = require("node:perf_hooks");

class Counter {
    constructor() {
        this.value = 0;
    }
    bump() {
        this.value += 1;
    }
}

function run(n) {
    const counter = new Counter();
    for (let i = 0; i < n; i += 1) {
        counter.bump();
    }
    return counter.value;
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

const [result, elapsedMs] = measure(() => run(5000));
console.log(result);
console.log(elapsedMs);
