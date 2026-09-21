// usage: node jsum.js LABEL file.json -> one RESULT line of Jest counts
const fs = require("fs"), path = require("path");
const [label, file] = process.argv.slice(2);
if (!fs.existsSync(file)) { console.log(`RESULT ${label} no-json (run crashed before writing results)`); process.exit(0); }
const r = JSON.parse(fs.readFileSync(path.resolve(file), "utf8"));
const bad = r.testResults.filter(t => t.status === "failed").length;
console.log(`RESULT ${label} files ${r.numPassedTestSuites}/${r.numTotalTestSuites} passed, ${bad} failed | tests passed ${r.numPassedTests} failed ${r.numFailedTests} pending ${r.numPendingTests} total ${r.numTotalTests}`);
