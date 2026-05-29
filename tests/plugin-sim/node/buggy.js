function getValue(record) {
  return record.value;
}

function main() {
  const records = [{ value: 10 }, null];
  for (const r of records) {
    console.log(getValue(r));
  }
}

main();
